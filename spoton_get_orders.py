from curl_cffi import requests
from urllib.parse import urlparse, parse_qs


def run(headers, user_input):
    """Get restaurant orders from SpotOn Restaurant Reporting. Auto-detects location and defaults to today."""
    base_url = BASE_URL

    cookie = headers.get("Cookie", "")
    if not cookie:
        return {'status_code': 401, 'body': {'error': 'No session cookie provided'}}

    # Authenticate
    token, error = _get_reporting_token(cookie)
    if error:
        return {'status_code': 401, 'body': {'error': error}}

    # Auto-detect location if not provided
    location_key = user_input.get("location_key")
    if not location_key:
        location_key = _get_default_location(cookie, token)
        if not location_key:
            return {'status_code': 500, 'body': {'error': 'Could not auto-detect location'}}

    start_date = user_input.get("start_date")
    end_date = user_input.get("end_date")
    if not start_date:
        from datetime import date
        start_date = date.today().strftime("%Y-%m-%d")
    if not end_date:
        end_date = start_date

    start_key = int(start_date.replace("-", ""))

    # Build query params
    params = {
        "location_key": str(location_key),
        "date_range": {
            "startDate": f"{start_date}T00:00:00",
            "endDate": f"{end_date}T00:00:00"
        },
        "business_date_key": start_key
    }

    # Query report data
    query = """query getReport($queryFilter: QueryFilter!, $params: JSONObject) {
  reports: getReportsData(queryFilter: $queryFilter, params: $params) {
    results
    id
    templateName
  }
}"""

    variables = {
        "queryFilter": {"templateName": "orderlist"},
        "params": params
    }

    resp = requests.post(
        "https://restaurantreports.spoton.com/graphql",
        headers={
            "Cookie": cookie,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-app-name": "restaurant-reporting",
            "Authorization": f"Bearer {token}",
        },
        json={"operationName": "getReport", "variables": variables, "query": query},
        impersonate="chrome131",
        timeout=30
    )

    if resp.status_code == 401 or (resp.status_code == 200 and "Unauthenticated" in resp.text):
        return {'status_code': 401, 'body': {'error': 'Session expired or unauthorized'}}

    if resp.status_code != 200:
        return {'status_code': resp.status_code, 'body': {'error': f'API returned status {resp.status_code}'}}

    data = resp.json()
    if "errors" in data:
        return {'status_code': 500, 'body': {'error': data["errors"][0].get("message", "GraphQL error")}}

    reports = data.get("data", {}).get("reports", [])
    results = []
    for report in reports:
        results.extend(report.get("results", []))

    return {'status_code': 200, 'body': {'orders': results, 'count': len(results)}}


# === PRIVATE ===

def _get_reporting_token(cookie):
    """Authenticate with restaurant reporting via Okta OAuth flow."""
    try:
        resp = requests.get(
            "https://restaurantreports.spoton.com/api/v2/okta/signin",
            headers={"Cookie": cookie, "Accept": "text/html"},
            impersonate="chrome131",
            timeout=30,
            allow_redirects=False
        )
        if resp.status_code != 302:
            return None, "Failed to initiate auth flow"

        okta_url = resp.headers.get("location", "")
        if not okta_url:
            return None, "No redirect URL from signin"

        resp2 = requests.get(
            okta_url,
            headers={"Cookie": cookie, "Accept": "text/html"},
            impersonate="chrome131",
            timeout=30,
            allow_redirects=False
        )
        if resp2.status_code != 302:
            return None, "Okta session expired - re-authentication required"

        callback_url = resp2.headers.get("location", "")
        if not callback_url:
            return None, "No callback URL from Okta"

        parsed = urlparse(callback_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code:
            return None, "No authorization code received"

        resp3 = requests.get(
            "https://restaurantreports.spoton.com/api/v2/okta/authorization-code/callback",
            params={"code": code, "state": state},
            headers={"Cookie": cookie, "Accept": "application/json"},
            impersonate="chrome131",
            timeout=30
        )

        if resp3.status_code != 200:
            return None, "Failed to exchange authorization code"

        try:
            data = resp3.json()
        except Exception:
            return None, "Invalid response from token exchange"

        token = data.get("token")
        if not token:
            return None, "No token in response"

        return token, None

    except Exception as e:
        return None, f"Auth flow error: {str(e)}"


def _get_default_location(cookie, token):
    """Auto-detect first location from the user's account."""
    query = """query organizations($limit: Int, $offset: Int) {
  organizations(limit: $limit, offset: $offset) {
    locations {
      location_key
      name
    }
  }
}"""
    resp = requests.post(
        "https://restaurantreports.spoton.com/graphql",
        headers={
            "Cookie": cookie,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-app-name": "restaurant-reporting",
            "Authorization": f"Bearer {token}",
        },
        json={"operationName": "organizations", "variables": {"limit": 10, "offset": 0}, "query": query},
        impersonate="chrome131",
        timeout=30
    )
    if resp.status_code == 200:
        data = resp.json()
        orgs = data.get("data", {}).get("organizations", [])
        for org in orgs:
            locations = org.get("locations", [])
            if locations:
                return locations[0].get("location_key")
    return None
