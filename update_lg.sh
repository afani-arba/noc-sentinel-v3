#!/bin/bash
# ==============================================================
# BGP Looking Glass Update Script untuk NOC Sentinel
# ==============================================================
set -e

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
NC="\033[0m"

echo -e "${YELLOW}Memulai proses update BGP Looking Glass...${NC}"

echo -e "\n${GREEN}1. Menarik pembaruan dari GitHub...${NC}"
git pull origin main

echo -e "\n${GREEN}2. Rebuild Frontend (React)...${NC}"
cd frontend
npm install
npm run build
cd ..

echo -e "\n${GREEN}3. Restarting Backend Service...${NC}"
systemctl restart noc-sentinel-backend || pm2 restart noc-sentinel-backend

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}UPDATE SELESAI!${NC}"
echo -e "Silakan refresh browser Anda untuk melihat BGP Looking Glass."
echo -e "${GREEN}======================================================${NC}"
