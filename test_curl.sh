#!/bin/bash
IP="203.30.221.1:1088"
AUTH="suprayogi:2009Ogi"
echo "Testing curl to $IP..."
curl -k -u "$AUTH" -X POST "http://$IP/rest/ping" \
  -H "content-type: application/json" \
  -d '{"address": "8.8.8.8", "count": "3"}'
