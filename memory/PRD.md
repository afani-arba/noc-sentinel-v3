# NOC-SENTINEL - MikroTik Monitoring Tool v2.0

## Problem Statement
MikroTik monitoring tool for Ubuntu server with real SNMP monitoring and MikroTik REST API integration.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn/UI + Recharts
- **Backend**: FastAPI + pysnmp (SNMP monitoring) + MikroTik REST API (CRUD)
- **Database**: MongoDB (traffic history, device config, user management)
- **PDF Export**: jsPDF + jspdf-autotable

## What's Implemented (March 8, 2026)
- [x] Login page (JWT auth, 3 roles: administrator/viewer/user)
- [x] Dashboard: device selector, interface selector, real-time traffic/ping/jitter charts
- [x] PPPoE Users: CRUD via MikroTik REST API, device selector, search, online status
- [x] Hotspot Users: CRUD via MikroTik REST API, device selector, search, online status
- [x] Reports: daily/weekly/monthly from SNMP history, PDF export
- [x] Devices: SNMP + REST API config, test connection buttons, auto-polling
- [x] Admin: user management with 3 roles
- [x] SNMP polling: background task every 30s, traffic history stored in MongoDB
- [x] All mock data REMOVED - 100% real data from MikroTik

## MikroTik Requirements
- RouterOS v7.1+ (for REST API - PPPoE/Hotspot CRUD)
- SNMP enabled (for monitoring)
- REST API enabled (IP > Services > www-ssl or www)

## Default Credentials
- Username: admin / Password: admin123

## Backlog
- P1: WebSocket for real-time dashboard updates
- P1: Pagination for large user lists
- P2: User activity audit logs
- P2: Batch user import/export CSV
- P3: Email/Telegram alert notifications
