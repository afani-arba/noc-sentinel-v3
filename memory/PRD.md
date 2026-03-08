# NOC-SENTINEL - MikroTik Monitoring Tool v2.3

## Problem Statement
MikroTik monitoring tool for Ubuntu server with real SNMP monitoring and MikroTik API integration supporting both RouterOS v6 (legacy API) and RouterOS v7 (REST API).

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn/UI + Recharts
- **Backend**: FastAPI + pysnmp (SNMP monitoring) + MikroTik API (REST & Legacy)
- **Database**: MongoDB (traffic history, device config, user management)
- **PDF Export**: jsPDF + jspdf-autotable
- **MikroTik API Factory**: Supports both RouterOS v6 (port 8728/8729) and v7 (port 443/80)
- **Ping**: ICMP with TCP fallback to port 161/8728/443

## What's Implemented (March 8, 2026)
- [x] Login page (JWT auth, 3 roles: administrator/viewer/user)
- [x] Dashboard: device selector, interface selector, real-time traffic/ping/jitter charts
- [x] PPPoE Users: CRUD via MikroTik API, device selector, search, online status, **password display**
- [x] Hotspot Users: CRUD via MikroTik API, device selector, search, online status, **password display**
- [x] Reports: daily/weekly/monthly from SNMP history, PDF export
- [x] Devices: SNMP + API config, test connection buttons, auto-polling, **scrollable dialog**
- [x] Admin: user management with 3 roles
- [x] SNMP polling: background task every 30s, traffic history stored in MongoDB
- [x] All mock data REMOVED - 100% real data from MikroTik
- [x] **RouterOS v6/v7 Support**: API mode selector with auto port/SSL switching
- [x] **System Health Extended**: CPU/Memory Load, CPU Temp, Board Temp, Voltage, Power
- [x] **Device Info**: Identity, Board Name, ROS Version, Architecture
- [x] **Traffic History**: Time in WIB (UTC+7) timezone
- [x] **Ping & Jitter**: ICMP ping with TCP fallback, real-time graph

## MikroTik Requirements
### RouterOS v7.1+ (REST API mode)
- REST API enabled (IP > Services > www-ssl atau www)
- Default port: 443 (HTTPS) atau 80 (HTTP)

### RouterOS v6.x+ (API Protocol mode)
- API enabled (IP > Services > api atau api-ssl)
- Default port: 8728 (tanpa SSL) atau 8729 (dengan SSL)

### SNMP Requirements
- SNMP v2c enabled
- Extended SNMP OIDs for health metrics (temperature, voltage, power) require MikroTik-specific MIB

## Default Credentials
- Username: admin / Password: admin123

## Backlog
- P1: WebSocket for real-time dashboard updates
- P1: Pagination for large user lists
- P2: User activity audit logs
- P2: Batch user import/export CSV
- P3: Email/Telegram alert notifications
- P2: Verify PDF report generation with real data
- P2: Test user role permissions (Viewer, User restrictions)
