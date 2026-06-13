from curl_cffi import requests
from urllib.parse import urlparse, parse_qs


# FOH/BOH role classification
# FOH (Front of House): customer-facing roles
# BOH (Back of House): kitchen/prep roles
# Roles not matching either default to FOH
FOH_ROLES = {
    "server", "bartender", "lead bartender", "host", "hostess",
    "hospitality assistent", "hospitality assistant", "cashier",
    "barback", "busser", "food runner", "front of house",
}
BOH_ROLES = {
    "chef", "cook", "line cook", "prep cook", "dishwasher",
    "kitchen", "sous chef", "executive chef", "back of house",
    "grill", "fry", "sauté", "pastry",
}


def run(headers, user_input):
    """Get labor breakdown split into FOH and BOH percentages against net sales.

    Uses the Daily Sales Recap which provides labor cost per role and net sales
    in a single query. Roles are categorized as FOH (front of house) or BOH
    (back of house) based on role name. Auto-detects location and defaults to today.
    """
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

    # Convert dates to API format
    start_key = int(start_date.replace("-", ""))
    end_key = int(end_date.replace("-", ""))
    from datetime import datetime, timedelta
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    end_plus_10 = int((end_dt + timedelta(days=10)).strftime("%Y%m%d"))

    # Query Daily Sales Recap for labor by role + net sales
    query = """query dailySalesRecap($input: DailySalesRecapInput!) {
  reports: dailySalesRecap(input: $input) {
    name
    data {
      sales {
        category
        subtotal
        discounts
        voids
        refunds
      }
      labor {
        role_name
        shift_hours
        labor_total
      }
    }
  }
}"""

    variables = {
        "input": {
            "location_key": str(location_key),
            "date_range": {
                "startDate": f"{start_date}T06:00:00.000Z",
                "endDate": f"{end_date}T06:00:00.000Z"
            },
            "start_date": start_key,
            "end_date": end_key,
            "end_dt_plus_10_days": end_plus_10
        }
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
        json={"operationName": "dailySalesRecap", "variables": variables, "query": query},
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

    report = data.get("data", {}).get("reports", {})
    day_data_list = report.get("data", [])

    if not day_data_list:
        return {'status_code': 200, 'body': {
            'date': start_date,
            'total_labor_pct': 0.0,
            'foh_labor_pct': 0.0,
            'boh_labor_pct': 0.0,
            'net_sales': 0.0,
            'total_labor_cost': 0.0,
            'foh_labor_cost': 0.0,
            'boh_labor_cost': 0.0,
            'foh_hours': 0.0,
            'boh_hours': 0.0,
            'role_breakdown': []
        }}

    # Aggregate across all days in the range
    total_net_sales = 0.0
    foh_labor_cost = 0.0
    boh_labor_cost = 0.0
    foh_hours = 0.0
    boh_hours = 0.0
    role_breakdown = []

    for day_data in day_data_list:
        # Calculate net sales = subtotal - discounts - voids (SpotOn's formula)
        sales = day_data.get("sales", [])
        for s in sales:
            subtotal = s.get("subtotal", 0) or 0
            discounts = s.get("discounts", 0) or 0
            voids = s.get("voids", 0) or 0
            total_net_sales += subtotal - discounts - voids

        # Categorize labor by role into FOH/BOH
        labor = day_data.get("labor", [])
        for l in labor:
            role_name = l.get("role_name", "")
            hours = l.get("shift_hours", 0) or 0
            cost = l.get("labor_total", 0) or 0
            role_lower = role_name.lower().strip()

            if role_lower in BOH_ROLES or any(boh in role_lower for boh in BOH_ROLES):
                category = "BOH"
                boh_labor_cost += cost
                boh_hours += hours
            elif role_lower in FOH_ROLES or any(foh in role_lower for foh in FOH_ROLES):
                category = "FOH"
                foh_labor_cost += cost
                foh_hours += hours
            else:
                # Default unmatched roles to FOH (managers, admin, etc.)
                category = "FOH"
                foh_labor_cost += cost
                foh_hours += hours

            role_breakdown.append({
                "role": role_name,
                "category": category,
                "hours": round(hours, 2),
                "labor_cost": round(cost, 2)
            })

    total_labor_cost = foh_labor_cost + boh_labor_cost

    # Calculate percentages
    if total_net_sales > 0:
        total_labor_pct = round(total_labor_cost / total_net_sales * 100, 1)
        foh_labor_pct = round(foh_labor_cost / total_net_sales * 100, 1)
        boh_labor_pct = round(boh_labor_cost / total_net_sales * 100, 1)
    else:
        total_labor_pct = 0.0
        foh_labor_pct = 0.0
        boh_labor_pct = 0.0

    return {'status_code': 200, 'body': {
        'date': start_date if start_date == end_date else f"{start_date} to {end_date}",
        'total_labor_pct': total_labor_pct,
        'foh_labor_pct': foh_labor_pct,
        'boh_labor_pct': boh_labor_pct,
        'net_sales': round(total_net_sales, 2),
        'total_labor_cost': round(total_labor_cost, 2),
        'foh_labor_cost': round(foh_labor_cost, 2),
        'boh_labor_cost': round(boh_labor_cost, 2),
        'foh_hours': round(foh_hours, 2),
        'boh_hours': round(boh_hours, 2),
        'role_breakdown': role_breakdown
    }}


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
