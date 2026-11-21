"""iFind HTTP client. Credentials remain in runner memory."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

class Client:
    def __init__(self):
        self.token = None

    def post(self, path, payload=None, authenticated=True):
        headers = {"Content-Type": "application/json", "ifindlang": "cn"}
        if authenticated:
            if not self.token:
                self.authenticate()
            headers["access_token"] = self.token
        else:
            refresh = os.environ.get("IFIND_REFRESH_TOKEN", "").strip()
            if not refresh:
                raise RuntimeError("IFIND_REFRESH_TOKEN is required")
            headers["refresh_token"] = refresh
        request = Request("https://quantapi.51ifind.com/api/v1/" + path,
                          data=json.dumps(payload or {}).encode(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=45) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError("iFind HTTP status " + str(exc.code)) from None
        except (URLError, ValueError):
            raise RuntimeError("iFind network or response failure") from None
        if result.get("errorcode") not in (None, 0, "0"):
            raise RuntimeError("iFind error code " + str(result.get("errorcode")))
        return result

    def authenticate(self):
        result = self.post("get_access_token", authenticated=False)
        self.token = (result.get("data") or {}).get("access_token") or result.get("access_token")
        if not self.token:
            raise RuntimeError("iFind did not return an access token")

if __name__ == "__main__":
    client = Client()
    client.authenticate()
    print("iFind authentication succeeded")
    data = client.post("real_time_quotation", {"codes":"000300.SH","indicators":"latest"})
    if not data.get("tables"):
        raise RuntimeError("iFind quotation returned no tables")
    print("iFind quotation succeeded")
