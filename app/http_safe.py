import httpx

from .security import is_safe_public_url

REDIRECT_STATUSES = (301, 302, 303, 307, 308)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def redirect_target(response: httpx.Response, current_url: str) -> str | None:
    if response.status_code not in REDIRECT_STATUSES:
        return None
    location = response.headers.get("location")
    if not location:
        return None
    return str(httpx.URL(current_url).join(location))


def safe_get_sync(
    client: httpx.Client,
    url: str,
    headers: dict | None = None,
    max_redirects: int = 5,
) -> httpx.Response | None:
    current = url
    for _ in range(max_redirects + 1):
        if not is_safe_public_url(current):
            return None
        response = client.get(current, headers=headers, follow_redirects=False)
        target = redirect_target(response, current)
        if target is None:
            return response
        current = target
    return None


async def safe_get_async(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    max_redirects: int = 5,
) -> httpx.Response | None:
    current = url
    for _ in range(max_redirects + 1):
        if not is_safe_public_url(current):
            return None
        response = await client.get(current, headers=headers, follow_redirects=False)
        target = redirect_target(response, current)
        if target is None:
            return response
        current = target
    return None
