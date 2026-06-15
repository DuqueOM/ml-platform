"""
Policy layer — gate determinista, NO LLM.

INVARIANTE (§F2.2): NINGUNA respuesta final sale sin pasar estos checks.
Sin excepciones, ni siquiera smalltalk que mencione productos.

Fase 1: checks básicos sobre el contexto del loop.
Fase 2: políticas como datos en policies/*.yaml con decision_id para audit trail.
"""
from .schemas import Verdict

def check_policy(loop_context) -> Verdict:
    """Valida respuesta contra políticas deterministas.
    
    Args:
        loop_context: Instancia de AgentLoop con estado completo
    
    Returns:
        Verdict con aprobación o violaciones
    """
    violations = []
    
    # Check 1: Si mencionó productos, DEBE haber consultado stock/precio
    response_lower = loop_context.final_response.lower()
    product_mentioned = any(
        keyword in response_lower
        for keyword in ["coca", "pepsi", "frijol", "arroz", "leche", "pan", "huevo"]
    )
    
    if product_mentioned:
        # Verificar que se hayan ejecutado tools de inventory/pricing
        tools_used = {obs.tool for obs in loop_context.observations}
        
        if "inventory_lookup" not in tools_used and "alias_lookup" not in tools_used:
            violations.append("product_mentioned_without_inventory_check")
        
        # Verificar que no mencione "disponible" o "en stock" sin confirmación
        if any(word in response_lower for word in ["disponible", "en stock", "tenemos"]):
            if not any(obs.ok and obs.tool == "inventory_lookup" for obs in loop_context.observations):
                violations.append("stock_claimed_without_confirmation")
    
    # Check 2: Si mencionó precio, DEBE estar en observations
    if any(word in response_lower for word in ["$", "peso", "cuesta", "precio"]):
        pricing_obs = [obs for obs in loop_context.observations if obs.tool == "pricing_lookup" and obs.ok]
        if not pricing_obs:
            violations.append("price_mentioned_without_lookup")
    
    # Check 3: Si intent=order_create, DEBE ser dry_run en Fase 1
    if loop_context.route.intent == "order_create":
        order_obs = [obs for obs in loop_context.observations if obs.tool == "order_create"]
        if order_obs:
            for obs in order_obs:
                if not obs.data.get("dry_run", True):
                    violations.append("order_create_not_dry_run_in_phase1")
    
    # Check 4: No promesas ilegales (entrega inmediata, descuentos no autorizados)
    illegal_promises = ["entrega inmediata", "gratis hoy", "50% de descuento", "regalo"]
    if any(promise in response_lower for promise in illegal_promises):
        violations.append("illegal_promise_detected")
    
    # Check 5: Tono profesional (no groserías, no ALL CAPS excesivo)
    if response_lower.count("!!!") > 1 or len([c for c in loop_context.final_response if c.isupper()]) > len(loop_context.final_response) * 0.5:
        violations.append("tone_unprofessional")
    
    # Decisión
    approved = len(violations) == 0
    escalate_to = None if approved else 3  # Si falla, escalar a Tier 3 (juez)
    
    return Verdict(
        approved=approved,
        violations=violations,
        escalate_to_tier=escalate_to,
        policy_version="0.1.0",
        decision_id=""  # TODO: generar UUID en Fase 2
    )
