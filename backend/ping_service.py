"""
Ping Service — ICMP & TCP connectivity checks.
Digunakan oleh polling untuk mengukur latency/reachability.
Tidak menggunakan SNMP sama sekali.
"""
import asyncio
import logging
import re

logger = logging.getLogger(__name__)


async def ping_host(host: str, count: int = 4, timeout: int = 5) -> dict:
    """
    Real ICMP ping ke 8.8.8.8 (Google) dan 1.1.1.1 (Cloudflare).
    Mengembalikan hasil terbaik (latency terendah) dari kedua target.
    Parameter 'host' dipertahankan untuk kompatibilitas API namun tidak digunakan
    sebagai ping target — ping selalu ke internet (bukan ke MikroTik-nya).
    """
    results = await asyncio.gather(
        _icmp_ping("8.8.8.8", count=count, timeout=timeout),
        _icmp_ping("1.1.1.1", count=count, timeout=timeout),
        return_exceptions=True
    )

    valid = [r for r in results if isinstance(r, dict) and r.get("reachable")]

    if not valid:
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}

    # Kembalikan jalur internet terbaik (avg ping terendah)
    best = min(valid, key=lambda r: r.get("avg", 9999))
    return best


async def _icmp_ping(target: str, count: int = 4, timeout: int = 5) -> dict:
    """
    Real ICMP ping menggunakan system ping command.
    Berjalan di Linux (server) dengan binary ping standar.
    """
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", str(timeout), "-q", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout * count + 5
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="ignore")

        # Parse packet loss
        loss = 100
        loss_match = re.search(r"(\d+)%\s+packet\s+loss", output)
        if loss_match:
            loss = int(loss_match.group(1))

        # Parse rtt min/avg/max/mdev
        rtt_match = re.search(
            r"rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
            output
        )
        if rtt_match:
            return {
                "reachable": loss < 100,
                "min":    round(float(rtt_match.group(1)), 2),
                "avg":    round(float(rtt_match.group(2)), 2),
                "max":    round(float(rtt_match.group(3)), 2),
                "jitter": round(float(rtt_match.group(4)), 2),
                "loss":   loss,
                "target": target,
            }

        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100, "target": target}

    except Exception as e:
        logger.debug(f"ICMP ping ke {target} gagal: {e}")
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100, "target": target}


async def tcp_ping(host: str, ports: list, count: int = 3, timeout: int = 2) -> dict:
    """
    TCP ping fallback — cek reachability via TCP handshake.
    Berguna jika ICMP diblok tapi TCP port terbuka.
    """
    import time
    latencies = []

    for _ in range(count):
        for port in ports:
            try:
                start = time.time()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout
                )
                latency = (time.time() - start) * 1000
                latencies.append(latency)
                writer.close()
                await writer.wait_closed()
                break
            except Exception:
                continue

    if latencies:
        avg = sum(latencies) / len(latencies)
        min_lat = min(latencies)
        max_lat = max(latencies)
        jitter = sum(abs(l - avg) for l in latencies) / len(latencies) if len(latencies) > 1 else 0
        return {
            "reachable": True,
            "min":    round(min_lat, 2),
            "avg":    round(avg, 2),
            "max":    round(max_lat, 2),
            "jitter": round(jitter, 2),
            "loss":   round((count - len(latencies)) / count * 100),
        }

    return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
