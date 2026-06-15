"""
Loop formal del agente — 7 estaciones según §F1.6 del plan.

Flujo completo:
  route → plan → tools → observe → reflect → critic → policy → finalize
    E4B    tierN   app     app      tierN   tierN/N+1  determinista  tierN

Profundidad adaptativa (v3):
  - reflect: SOLO si tool-fail o risk>=medium (no en todos los casos)
  - critic: tier N o N+1 con prompt de verificador (distinto al de generación)
  - policy: gate determinista — NINGUNA respuesta sale sin pasar

Stop conditions:
  - max_iterations alcanzado
  - finality=clarify dos veces seguidas → UNA pregunta directa
  - oscilación → plantilla segura
  - latency_budget_ms agotado → respuesta parcial segura + flag
"""
import time
import yaml
from pathlib import Path
from typing import Optional

from .schemas import Route, RequestBudget, ToolCall, Observation, Verdict
from .router import route as classify_message
from .tiers import call_tier, extract_content, extract_usage
from . import tools

# Cargar budgets desde YAML
BUDGETS_PATH = Path(__file__).parent.parent / "budgets.yaml"
BUDGETS = yaml.safe_load(BUDGETS_PATH.read_text())

def get_budget(intent: str) -> RequestBudget:
    """Obtiene presupuesto para un intent específico.
    
    Args:
        intent: Intent clasificado por el router
    
    Returns:
        RequestBudget con límites para este request
    """
    budget_dict = BUDGETS.get(intent, BUDGETS["default"])
    return RequestBudget(**budget_dict)

class AgentLoop:
    """Loop ejecutor del agente — mantiene estado durante el request."""
    
    def __init__(self, message: str, customer_phone: str = ""):
        self.message = message
        self.customer_phone = customer_phone
        
        # Estado del loop
        self.route: Optional[Route] = None
        self.budget: Optional[RequestBudget] = None
        self.iterations = 0
        self.tool_calls_made = 0
        self.reflections_made = 0
        self.observations: list[Observation] = []
        self.final_response: Optional[str] = None
        self.verdict: Optional[Verdict] = None
        
        # Métricas
        self.start_time = time.time()
        self.latency_ms = {}
        self.tokens_by_tier = {}
    
    def run(self) -> dict:
        """Ejecuta el loop completo y retorna resultado.
        
        Returns:
            Dict con response, route, verdict, latency, etc.
        """
        # 1. Route (Tier 0)
        t0 = time.time()
        self.route = classify_message(self.message)
        self.latency_ms["route"] = int((time.time() - t0) * 1000)
        
        # Obtener presupuesto para este intent
        self.budget = get_budget(self.route.intent)
        
        # Escalación objetiva: si confidence < 0.70, sube un tier
        tier_to_use = self.route.tier
        if self.route.confidence < 0.70 and tier_to_use < 3:
            tier_to_use += 1
        
        # 2. Plan (tierN genera lista de tools a ejecutar)
        t1 = time.time()
        plan_response = self._plan_phase(tier_to_use)
        self.latency_ms["plan"] = int((time.time() - t1) * 1000)
        
        # 3. Tools (la APP ejecuta, no el modelo)
        t2 = time.time()
        tool_calls = self._extract_tool_calls(plan_response)
        self._execute_tools(tool_calls)
        self.latency_ms["tools"] = int((time.time() - t2) * 1000)
        
        # 4. Reflect (condicional: solo si tool-fail o risk>=medium)
        if self._should_reflect():
            t3 = time.time()
            self._reflect_phase(tier_to_use)
            self.latency_ms["reflect"] = int((time.time() - t3) * 1000)
        
        # 5. Generate response
        t4 = time.time()
        self.final_response = self._generate_response(tier_to_use)
        self.latency_ms["generate"] = int((time.time() - t4) * 1000)
        
        # 6. Critic (verificación cruzada para risk>=medium)
        if self.route.risk in ["medium", "high"]:
            t5 = time.time()
            critic_approved = self._critic_phase(tier_to_use)
            self.latency_ms["critic"] = int((time.time() - t5) * 1000)
            
            if not critic_approved:
                # Re-generar o escalar
                self.final_response = self._generate_response(min(tier_to_use + 1, 3))
        
        # 7. Policy gate (determinista — OBLIGATORIO)
        from .policy import check_policy
        self.verdict = check_policy(self)
        
        if not self.verdict.approved:
            # Respuesta segura por defecto
            self.final_response = self._safe_fallback_response()
        
        # 8. Finalize
        return self._finalize()
    
    def _plan_phase(self, tier: int) -> dict:
        """Fase de planning — pide al modelo qué tools usar.
        
        Args:
            tier: Tier a usar para planning
        
        Returns:
            Response del modelo con plan de herramientas
        """
        # Prompt simplificado para Fase 1 (sin tool schema formal)
        prompt = f"""El cliente dice: "{self.message}"

Intent clasificado: {self.route.intent}
Risk: {self.route.risk}
Ambiguity: {self.route.ambiguity}

Herramientas disponibles:
- alias_lookup(text): busca product_ids por nombre coloquial
- inventory_lookup(product_id): verifica stock
- pricing_lookup(product_id): consulta precio
- order_status(order_id): estado de un pedido
- semantic_retrieval(query): busca políticas/promociones

Lista las herramientas que necesitas (máx {self.budget.max_tool_calls}), una por línea:
tool_name(arg1="...", arg2="...")

Si no necesitas herramientas, responde: NONE
"""
        
        messages = [
            {"role": "system", "content": "Eres un asistente de tienda. Planea qué herramientas necesitas para responder."},
            {"role": "user", "content": prompt}
        ]
        
        response = call_tier(tier, messages, max_tokens=256, temperature=0)
        self._track_usage(tier, response)
        return response
    
    def _extract_tool_calls(self, plan_response: dict) -> list[ToolCall]:
        """Extrae ToolCalls del plan generado.
        
        Args:
            plan_response: Response del tier con el plan
        
        Returns:
            Lista de ToolCall a ejecutar
        """
        content = extract_content(plan_response)
        
        if "NONE" in content.upper():
            return []
        
        # Parseo simple (mejorará en Fase 2 con function calling)
        tool_calls = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if "(" in line and ")" in line:
                tool_name = line.split("(")[0].strip()
                # Parseo básico de args (mejorará)
                args_str = line.split("(")[1].split(")")[0]
                
                # Por ahora, solo soportamos tool(text="...") simple
                if tool_name in tools.REGISTRY:
                    args = {}
                    if "=" in args_str:
                        # Extraer arg simple
                        key, val = args_str.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"\'')
                        args[key] = val
                    
                    tool_calls.append(ToolCall(tool=tool_name, args=args))
        
        return tool_calls[:self.budget.max_tool_calls]
    
    def _execute_tools(self, tool_calls: list[ToolCall]):
        """Ejecuta las herramientas y almacena observaciones.
        
        Args:
            tool_calls: Lista de ToolCall a ejecutar
        """
        for tc in tool_calls:
            obs = tools.run(tc)
            self.observations.append(obs)
            self.tool_calls_made += 1
    
    def _should_reflect(self) -> bool:
        """Decide si ejecutar fase de reflexión (condicional, v3).
        
        Returns:
            True si debe reflejar, False si no
        """
        # Reflect SOLO si:
        # 1. Alguna tool falló
        # 2. risk >= medium
        
        if self.route.risk in ["medium", "high"]:
            return True
        
        if any(not obs.ok for obs in self.observations):
            return True
        
        return False
    
    def _reflect_phase(self, tier: int):
        """Fase de reflexión — contrasta plan con observaciones.
        
        Args:
            tier: Tier a usar
        """
        if self.reflections_made >= self.budget.max_reflections:
            return
        
        # Construir contexto de observaciones
        obs_summary = "\n".join([
            f"- {obs.tool}: {'OK' if obs.ok else f'FAILED ({obs.error})'} → {obs.data}"
            for obs in self.observations
        ])
        
        prompt = f"""Mensaje original: "{self.message}"

Observaciones de herramientas:
{obs_summary}

¿Falta información crítica? ¿Alguna herramienta contradijo la suposición? Responde en 1-2 oraciones."""
        
        messages = [
            {"role": "system", "content": "Reflexiona sobre los resultados de herramientas."},
            {"role": "user", "content": prompt}
        ]
        
        response = call_tier(tier, messages, max_tokens=128, temperature=0.3)
        self._track_usage(tier, response)
        self.reflections_made += 1
        
        # En Fase 1, solo loggeamos; en Fase 2, ajustamos el plan
    
    def _generate_response(self, tier: int) -> str:
        """Genera la respuesta final para el cliente.
        
        Args:
            tier: Tier a usar
        
        Returns:
            Respuesta en texto para el cliente
        """
        # Contexto de observaciones
        obs_context = "\n".join([
            f"{obs.tool}: {obs.data if obs.ok else f'ERROR: {obs.error}'}"
            for obs in self.observations
        ])
        
        prompt = f"""Cliente: "{self.message}"
Intent: {self.route.intent}

Información de herramientas:
{obs_context}

Genera una respuesta clara, corta y comercial para WhatsApp. NO inventes stock ni precios que no estén en las observaciones."""
        
        messages = [
            {"role": "system", "content": "Eres un asistente de tienda por WhatsApp. Responde de forma amable y profesional."},
            {"role": "user", "content": prompt}
        ]
        
        response = call_tier(tier, messages, max_tokens=256, temperature=0.7)
        self._track_usage(tier, response)
        
        return extract_content(response)
    
    def _critic_phase(self, tier: int) -> bool:
        """Fase de crítica — verificación cruzada de la respuesta.
        
        Args:
            tier: Tier base (puede usar tier+1 para verificar)
        
        Returns:
            True si aprobado, False si rechazado
        """
        # Prompt de VERIFICADOR (distinto al de generación)
        prompt = f"""Respuesta propuesta: "{self.final_response}"

Observaciones reales:
{chr(10).join([f"{obs.tool}: {obs.data}" for obs in self.observations if obs.ok])}

Verifica:
1. ¿Consistente con los datos de herramientas?
2. ¿Promete algo no confirmado en stock/precio?
3. ¿Claro para el cliente?

Responde SOLO: APPROVED o REJECTED"""
        
        messages = [
            {"role": "system", "content": "Eres un verificador. Valida respuestas contra datos reales."},
            {"role": "user", "content": prompt}
        ]
        
        response = call_tier(tier, messages, max_tokens=32, temperature=0)
        self._track_usage(tier, response)
        
        content = extract_content(response).strip().upper()
        return "APPROVED" in content
    
    def _safe_fallback_response(self) -> str:
        """Respuesta segura cuando policy gate rechaza.
        
        Returns:
            Respuesta genérica segura
        """
        return "Disculpa, no puedo procesar tu solicitud en este momento. ¿Podrías reformular tu pregunta o contactar directamente con la tienda?"
    
    def _track_usage(self, tier: int, response: dict):
        """Registra uso de tokens por tier.
        
        Args:
            tier: Número de tier
            response: Response del modelo
        """
        usage = extract_usage(response)
        if tier not in self.tokens_by_tier:
            self.tokens_by_tier[tier] = 0
        self.tokens_by_tier[tier] += usage.get("completion_tokens", 0)
    
    def _finalize(self) -> dict:
        """Construye resultado final con métricas.
        
        Returns:
            Dict con response, route, verdict, latency, etc.
        """
        total_latency = int((time.time() - self.start_time) * 1000)
        
        return {
            "response": self.final_response,
            "route": self.route.model_dump(),
            "verdict": self.verdict.model_dump() if self.verdict else None,
            "latency_ms": {
                **self.latency_ms,
                "total": total_latency
            },
            "tokens_by_tier": self.tokens_by_tier,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls_made,
            "observations": [obs.model_dump() for obs in self.observations]
        }
