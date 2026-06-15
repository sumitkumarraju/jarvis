import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web with DuckDuckGo. Returns a list of results with title, snippet, and URL."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results."
        return "\n\n".join(
            f"{i+1}. {r.get('title','')}\n{r.get('body','')}\n{r.get('href','')}"
            for i, r in enumerate(results)
        )
    except Exception as e:
        return f"Search error: {e}"


@tool
def fetch_page(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return readable text. Use after web_search to read a specific page."""
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception as e:
        return f"Fetch error: {e}"
