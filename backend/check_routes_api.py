import urllib.request, json
r = json.loads(urllib.request.urlopen('http://localhost:8000/api/routes?limit=10').read())
for route in r:
    rid = route['route_id']
    name = route.get('name') or rid[:8]
    print(f'{name} - status={route["status"]} - preds={route.get("prediction_count")} - risk={route.get("avg_delay_risk")} - stops={len(route.get("stops",[]))} - route_id={rid[:12]}')
