from safeops.domains.banking import DOMAIN as BANKING
from safeops.domains.base import Domain, DomainError, ToolSpec
from safeops.domains.ecommerce import DOMAIN as ECOMMERCE

DOMAINS: dict[str, Domain] = {d.name: d for d in (ECOMMERCE, BANKING)}


def get_domain(name: str) -> Domain:
    try:
        return DOMAINS[name]
    except KeyError:
        raise KeyError(f"Unknown domain '{name}'. Available: {', '.join(DOMAINS)}") from None


__all__ = ["DOMAINS", "Domain", "DomainError", "ToolSpec", "get_domain"]
