"""Environment-specific policy wrappers."""

from turbolane.policies.edge import EdgePolicy
from turbolane.policies.federated import FederatedPolicy

__all__ = ["EdgePolicy", "FederatedPolicy"]
