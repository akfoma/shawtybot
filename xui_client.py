import aiohttp
import asyncio
import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class XUIClient:
    def __init__(self):
        self.base_url = os.getenv('XUI_URL')
        self.path = os.getenv('XUI_PATH')
        self.bearer_token = os.getenv('XUI_BEARER_TOKEN')
        self._session = None

    def _get_api_url(self, endpoint):
        return f"{self.base_url}{self.path}/panel/api{endpoint}"

    @property
    def headers(self):
        return {
            'Authorization': f'Bearer {self.bearer_token}',
            'Content-Type': 'application/json'
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_connect=10, sock_read=15)
            connector = aiohttp.TCPConnector(limit=4, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(headers=self.headers, timeout=timeout, connector=connector)
        return self._session

    async def _retry_request(self, func, *args, max_retries: int = 3, **kwargs):
        """Retry request with exponential backoff"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
        raise last_error

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_new_uuid(self):
        async def _get_uuid():
            session = await self._get_session()
            async with session.get(
                self._get_api_url('/server/getNewUUID')
            ) as response:
                data = await response.json()
                if data.get('success'):
                    obj = data.get('obj', {})
                    if isinstance(obj, dict) and 'uuid' in obj:
                        uuid = str(obj['uuid']).strip()
                    elif isinstance(obj, str):
                        uuid = obj.strip()
                    else:
                        uuid = str(obj).strip()
                    logger.info("Generated new UUID from XUI")
                    return uuid
                else:
                    raise Exception(f"Failed to get UUID: {data.get('msg')}")
        return await self._retry_request(_get_uuid)

    async def add_client(self, inbound_id: int, email: str, uuid: str, limit_ip: int = 3, expiry_time: int = 0, total_gb: int = 0, flow: str = "xtls-rprx-vision"):
        async def _add_client():
            clients_config = [{
                "id": uuid,
                "email": email,
                "limitIp": limit_ip,
                "totalGB": total_gb,
                "expiryTime": expiry_time,
                "enable": True,
                "flow": flow
            }]

            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": clients_config})
            }

            logger.info("Adding XUI client email=%s inbound=%s expiry=%s totalGB=%s", email, inbound_id, expiry_time, total_gb)

            session = await self._get_session()
            async with session.post(
                self._get_api_url('/inbounds/addClient'),
                json=payload
            ) as response:
                result = await response.json()
                if not result.get('success'):
                    raise Exception(f"Failed to add client to inbound {inbound_id}: {result.get('msg')}")
                return result
        return await self._retry_request(_add_client)

    async def get_inbound_config(self, inbound_id: int):
        async def _get_config():
            session = await self._get_session()
            async with session.get(
                self._get_api_url(f'/inbounds/get/{inbound_id}')
            ) as response:
                result = await response.json()
                return result
        return await self._retry_request(_get_config)

    async def copy_client_to_inbound(self, target_inbound_id: int, source_inbound_id: int, email: str, flow: str = None):
        async def _copy_client():
            payload = {
                "sourceInboundId": source_inbound_id,
                "clientEmails": [email]
            }

            if flow is not None:
                payload["flow"] = flow

            logger.info("Copying XUI client email=%s to inbound=%s", email, target_inbound_id)

            session = await self._get_session()
            async with session.post(
                self._get_api_url(f'/inbounds/{target_inbound_id}/copyClients'),
                json=payload
            ) as response:
                result = await response.json()
                if not result.get('success'):
                    raise Exception(f"Failed to copy client to inbound {target_inbound_id}: {result.get('msg')}")
                return result
        return await self._retry_request(_copy_client)

    async def get_client_id_by_email(self, inbound_id: int, email: str) -> str | None:
        """Найти UUID клиента по email в конкретном inbound"""
        async def _get_client_id():
            config = await self.get_inbound_config(inbound_id)
            if not (config and config.get('success') and config.get('obj')):
                return None
            obj = config['obj']
            if 'settings' not in obj:
                return None
            settings = json.loads(obj['settings']) if isinstance(obj['settings'], str) else obj['settings']
            for client in settings.get('clients', []):
                if client.get('email') == email:
                    return client.get('id')
            return None
        return await self._retry_request(_get_client_id)

    async def get_client_id_by_uuid(self, inbound_id: int, uuid: str) -> str | None:
        """Найти ID клиента по UUID в конкретном inbound"""
        async def _get_client_id():
            config = await self.get_inbound_config(inbound_id)
            if not (config and config.get('success') and config.get('obj')):
                return None
            obj = config['obj']
            if 'settings' not in obj:
                return None
            settings = json.loads(obj['settings']) if isinstance(obj['settings'], str) else obj['settings']
            for client in settings.get('clients', []):
                if client.get('id') == uuid:
                    return uuid
            return None
        return await self._retry_request(_get_client_id)

    async def get_client_id_by_email_pattern(self, inbound_id: int, email_base: str) -> str | None:
        """Найти ID клиента по части email (без суффиксов) в конкретном inbound"""
        async def _get_client_id():
            config = await self.get_inbound_config(inbound_id)
            if not (config and config.get('success') and config.get('obj')):
                return None
            obj = config['obj']
            if 'settings' not in obj:
                return None
            settings = json.loads(obj['settings']) if isinstance(obj['settings'], str) else obj['settings']
            for client in settings.get('clients', []):
                client_email = client.get('email', '')
                # Check if email starts with the base (e.g., "user@domain" matches "user@domain_2")
                if client_email.startswith(email_base):
                    return client.get('id')
            return None
        return await self._retry_request(_get_client_id)

    async def delete_client(self, inbound_id: int, client_id: str):
        async def _delete_client():
            session = await self._get_session()
            async with session.post(
                self._get_api_url(f'/inbounds/{inbound_id}/delClient/{client_id}'),
            ) as response:
                try:
                    result = await response.json()
                except Exception:
                    result = {"success": False, "msg": f"HTTP error {response.status}"}
                if not result.get('success'):
                    raise Exception(f"Failed to delete client from inbound {inbound_id}: {result.get('msg')}")
                return result
        try:
            return await self._retry_request(_delete_client)
        except Exception as e:
            logger.warning(f"Failed to delete client from inbound {inbound_id}: {e}")
            raise
