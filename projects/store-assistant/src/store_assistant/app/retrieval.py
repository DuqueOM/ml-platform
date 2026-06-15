"""
Retrieval file-based con BM25 — antes que cualquier vector store.

Indexa policies/*.md y retrieval/data/*.md (políticas de tienda, promociones,
plantillas de objeciones) para exponer como tool `semantic_retrieval`.

NADA de stock/precio aquí — eso va por tools con APIs reales.
"""
from pathlib import Path
from rank_bm25 import BM25Okapi
from .schemas import Observation

class BM25Index:
    """Índice BM25 sobre archivos .md en un directorio."""
    
    def __init__(self, docs_dir: Path):
        self.docs_dir = Path(docs_dir)
        self.docs = []
        self.corpus = []
        self.bm25 = None
        
        if not self.docs_dir.exists():
            return
        
        # Cargar todos los .md
        for md_file in self.docs_dir.glob("*.md"):
            content = md_file.read_text()
            self.docs.append({
                "file": md_file.name,
                "content": content
            })
            # Tokenización simple (split por espacios)
            self.corpus.append(content.lower().split())
        
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
    
    def search(self, query: str, k: int = 3) -> list[dict]:
        """Busca los top-k documentos más relevantes.
        
        Args:
            query: Consulta del usuario
            k: Número de resultados
        
        Returns:
            Lista de dicts {"file": str, "content": str, "score": float}
        """
        if not self.bm25:
            return []
        
        query_tokens = query.lower().split()
        scores = self.bm25.get_scores(query_tokens)
        
        # Top-k índices
        top_k_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        
        results = []
        for idx in top_k_idx:
            if scores[idx] > 0:  # Solo resultados con score > 0
                results.append({
                    "file": self.docs[idx]["file"],
                    "content": self.docs[idx]["content"],
                    "score": float(scores[idx])
                })
        
        return results

# Índice global (se inicializa al import)
_POLICIES_DIR = Path(__file__).parent.parent / "retrieval" / "data" / "policies"
_policies_index = BM25Index(_POLICIES_DIR)

def semantic_retrieval(query: str, k: int = 3) -> Observation:
    """Tool: búsqueda semántica sobre políticas/promociones de tienda.
    
    Args:
        query: Pregunta del cliente o tema a buscar
        k: Número de documentos a retornar
    
    Returns:
        Observation con los top-k documentos
    """
    results = _policies_index.search(query, k=k)
    
    return Observation(
        tool="semantic_retrieval",
        ok=bool(results),
        data={"results": results, "query": query},
        error=None if results else "no_results"
    )

# Registrar en el REGISTRY de tools
from .tools import tool
tool("semantic_retrieval")(semantic_retrieval)
