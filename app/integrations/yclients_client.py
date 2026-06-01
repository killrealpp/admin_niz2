import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class YClientsError(RuntimeError):
    pass


class YClientsClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.yclients_base_url.rstrip("/")
        self.company_id = self.settings.yclients_company_id

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {self.settings.yclients_partner_token}, "
                f"User {self.settings.yclients_user_token}"
            ),
        }

    def get_book_services(self) -> list[dict[str, Any]]:
        data = self._request("GET", f"/book_services/{self.company_id}")
        return self._as_list(data)

    def get_book_staff(self, service_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if service_id:
            params["service_ids[]"] = service_id
        data = self._request("GET", f"/book_staff/{self.company_id}", params=params)
        return self._as_list(data)

    def get_book_times(
        self,
        *,
        staff_id: str,
        date: str,
        service_id: str,
    ) -> list[Any]:
        params = {"service_ids[]": service_id}
        data = self._request(
            "GET",
            f"/book_times/{self.company_id}/{staff_id}/{date}",
            params=params,
        )
        return self._as_list(data)

    def create_book_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/book_record/{self.company_id}", json=payload)

    def delete_record(self, record_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/record/{self.company_id}/{record_id}")

    def get_records(
        self,
        *,
        start_date: str,
        end_date: str,
        page: int = 1,
        count: int = 200,
    ) -> list[dict[str, Any]]:
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "count": count,
        }
        data = self._request("GET", f"/records/{self.company_id}", params=params)
        return self._as_list(data)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.settings.yclients_partner_token or not self.settings.yclients_user_token:
            raise YClientsError("YCLIENTS tokens are not configured")
        if not self.company_id:
            raise YClientsError("YCLIENTS company id is not configured")

        url = f"{self.base_url}{path}"
        attempts = 3 if method.upper() == "GET" else 1
        last_error: httpx.HTTPError | None = None
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=30, trust_env=self.settings.http_trust_env) as client:
                    response = client.request(method, url, headers=self.headers, **kwargs)
                break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise YClientsError(f"YCLIENTS request failed: {exc}") from exc
                logger.warning(
                    "YCLIENTS %s %s transient error attempt=%s/%s: %s",
                    method,
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                time.sleep(0.8 * attempt)
            except httpx.HTTPError as exc:
                raise YClientsError(f"YCLIENTS request failed: {exc}") from exc
        else:
            raise YClientsError(f"YCLIENTS request failed: {last_error}")

        if response.status_code >= 400:
            logger.warning(
                "YCLIENTS %s %s failed status=%s body=%s",
                method,
                path,
                response.status_code,
                response.text[:1000],
            )
            raise YClientsError(
                f"YCLIENTS returned HTTP {response.status_code} for {path}: {response.text[:500]}"
            )

        if not response.text.strip():
            return {"success": True, "data": {}}
        payload = response.json()
        if isinstance(payload, dict) and payload.get("success") is False:
            raise YClientsError(str(payload.get("meta") or payload.get("message") or payload))
        return payload

    @staticmethod
    def _as_list(payload: dict[str, Any]) -> list[Any]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("services", "staff", "times", "slots", "records"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return [data]
        return []
