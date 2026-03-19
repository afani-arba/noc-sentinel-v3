import asyncio
import logging
from datetime import datetime, timedelta
from core.db import get_db

logger = logging.getLogger(__name__)

def _now():
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()

async def auto_isolir_loop():
    logger.info("Auto Isolir background task started (checks every minute)")
    while True:
        try:
            now = datetime.now()
            db = get_db()
            settings = await db.billing_settings.find_one({}, {"_id": 0}) or {}
            
            is_enabled = settings.get("auto_isolir_enabled", False)
            target_time_str = settings.get("auto_isolir_time", "00:05")
            grace_days = settings.get("auto_isolir_grace_days", 1)
            
            current_time_str = now.strftime("%H:%M")
            if is_enabled and current_time_str == target_time_str:
                # Cek apakah sudah berjalan hari ini
                today_str = now.strftime("%Y-%m-%d")
                run_log = await db.system_logs.find_one({"type": "auto_isolir_run", "date": today_str})
                
                if not run_log:
                    logger.info(f"Executing Auto Isolir for {today_str}...")
                    
                    target_due_date = (now.date() - timedelta(days=grace_days)).isoformat()
                    
                    # Cari semua invoice belum lunas dan melewati batas toleransi due_date
                    invoices = await db.invoices.find({
                        "status": {"$in": ["unpaid", "overdue"]},
                        "due_date": {"$lt": target_due_date}, # strictly less than target
                        "mt_disabled": {"$ne": True}
                    }).to_list(None)
                    
                    from mikrotik_api import get_api_client
                    success, failed, skipped = 0, 0, 0
                    
                    for inv in invoices:
                        customer = await db.customers.find_one({"id": inv.get("customer_id")})
                        if not customer:
                            skipped += 1
                            continue
                        device = await db.devices.find_one({"id": customer.get("device_id")})
                        if not device:
                            skipped += 1
                            continue
                        
                        try:
                            mt = get_api_client(device)
                            username = customer.get("username", "")
                            svc = customer.get("service_type", "pppoe")
                            if svc == "pppoe":
                                await mt.disable_pppoe_user(username)
                            else:
                                await mt.disable_hotspot_user(username)
                            
                            # Tandai sebagai overdue dan disable=True
                            await db.invoices.update_one(
                                {"id": inv["id"]}, 
                                {"$set": {"status": "overdue", "mt_disabled": True}}
                            )
                            success += 1
                            
                            # Kirim WA notifikasi isolir
                            phone = customer.get("phone")
                            template = settings.get("wa_template_isolir", "")
                            wa_type = settings.get("wa_gateway_type", "fonnte")
                            url = settings.get("wa_api_url", "https://api.fonnte.com/send")
                            token = settings.get("wa_token", "")
                            
                            if phone and template and url:
                                pkg = await db.billing_packages.find_one({"id": inv.get("package_id")})
                                
                                def _rupiah(amount: int) -> str:
                                    return f"Rp {amount:,.0f}".replace(",", ".")
                                
                                msg = template.replace("{customer_name}", customer.get("name", ""))
                                msg = msg.replace("{invoice_number}", inv.get("invoice_number", ""))
                                msg = msg.replace("{package_name}", pkg.get("name", "") if pkg else "")
                                msg = msg.replace("{total}", _rupiah(inv.get("total", 0)))
                                msg = msg.replace("{period}", f"{inv.get('period_start')} s/d {inv.get('period_end')}")
                                msg = msg.replace("{due_date}", inv.get("due_date", ""))
                                
                                try:
                                    import httpx
                                    async with httpx.AsyncClient(timeout=10) as client:
                                        if wa_type == "fonnte":
                                            await client.post(url, headers={"Authorization": token}, data={"target": phone, "message": msg, "countryCode": "62"})
                                        elif wa_type == "wablas":
                                            await client.post(url, headers={"Authorization": token}, json={"phone": phone, "message": msg})
                                        else:
                                            headers = {"Authorization": token} if token else {}
                                            await client.post(url, headers=headers, json={"phone": phone, "message": msg})
                                except Exception as we:
                                    logger.error(f"Auto Isolir WA error for {customer.get('name')}: {we}")
                                    
                        except Exception as e:
                            logger.error(f"Auto Isolir failed for {customer.get('name', '?')}: {e}")
                            failed += 1
                    
                    # Catat bahwa isolir sudah dijalankan hari ini
                    await db.system_logs.insert_one({
                        "type": "auto_isolir_run",
                        "date": today_str,
                        "success": success,
                        "failed": failed,
                        "timestamp": _now()
                    })
                    logger.info(f"Auto Isolir finished: {success} disabled, {failed} failed, {skipped} skipped.")
                    
        except Exception as e:
            logger.error(f"Error in auto_isolir_loop: {e}")
            
        await asyncio.sleep(60) # istirahat 60 detik sebelum cek jam lagi
