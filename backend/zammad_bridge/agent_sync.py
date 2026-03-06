import logging
from .client import ZammadClient

logger = logging.getLogger(__name__)


def sync_agent_created(user):
    """Create agent in Zammad when an IT worker is created."""
    try:
        client = ZammadClient()
        client.get_or_create_agent(user)
    except Exception as e:
        logger.error(f'Zammad agent sync failed for user {user.username}: {e}')
        raise


def sync_agent_companies(user):
    """Sync agent's Zammad group membership to match user.companies."""
    try:
        client = ZammadClient()
        agent_id = client.get_or_create_agent(user)
        companies = user.companies.all()
        group_ids = [client.get_or_create_group(c.name) for c in companies]
        client.set_agent_groups(agent_id, group_ids)
    except Exception as e:
        logger.error(f'Zammad group sync failed for user {user.username}: {e}')
        raise
