# Dual-Session Telegram Listener Guide

## Overview

This guide provides multiple options for running separate Ukraine and Russia Telegram sessions, optionally with different IP addresses via Mullvad VPN.

## Why Dual Sessions?

- **API Quota Split**: Distribute Telegram/DeepL API usage across two accounts
- **Channel Access**: One account for Ukraine channels, another for Russia channels
- **Original Architecture**: Restore your 2-year-old working setup

---

## Option 1: Simple Dual-Session (Same IP) ⭐ EASIEST

**Pros:** Simple, no VPN needed, works immediately
**Cons:** Both sessions from same IP (Telegram allows this, but may apply stricter rate limits)

### Setup:
```bash
# 1. Setup both sessions
python3 setup_dual_sessions.py

# 2. Run the dual-session listener
python3 src/listener-dual-session.py
```

### Docker:
Update `docker-compose.yml` to use `listener-dual-session.py` instead of `listener-db.py`.

---

## Option 2: Split Sessions with Gluetun VPN 🔒 RECOMMENDED

**Pros:** Each session gets different IP, clean separation, Docker-native
**Cons:** Requires Mullvad Wireguard setup

### Prerequisites:
1. Mullvad account
2. Generate Wireguard configs for 2 different locations:
   - Go to https://mullvad.net/account/wireguard-config
   - Generate config for Sweden (Ukraine session)
   - Generate config for Netherlands (Russia session)

### Setup:
```bash
# 1. Add Wireguard keys to .env
cat >> .env << EOF
MULLVAD_PRIVATE_KEY_UKRAINE=your_sweden_private_key
MULLVAD_ADDRESS_UKRAINE=your_sweden_address
MULLVAD_PRIVATE_KEY_RUSSIA=your_netherlands_private_key
MULLVAD_ADDRESS_RUSSIA=your_netherlands_address
EOF

# 2. Setup sessions
python3 setup_dual_sessions.py

# 3. Run with Docker Compose
docker-compose -f docker-compose-gluetun.yml up -d
```

### Verify different IPs:
```bash
docker exec telegram_ukraine wget -qO- https://am.i.mullvad.net/ip
# Should show Swedish IP

docker exec telegram_russia wget -qO- https://am.i.mullvad.net/ip
# Should show Netherlands IP
```

---

## Option 3: Sequential with VPN (Safest)

**Pros:** Only one session active at a time, no IP conflict risk
**Cons:** Not truly concurrent, channels monitored in shifts

Run Ukraine session 12 hours, then Russia session 12 hours.

```bash
chmod +x run_dual_with_vpn.sh
./run_dual_with_vpn.sh sequential
```

---

## Option 4: Single Session (Rejoin Channels) 🔄 SIMPLEST

**Pros:** Simplest solution, uses existing fixed code
**Cons:** Need to manually rejoin 69 Ukraine or 38 Russia channels

### Steps:
1. Pick your primary account (whichever has more channels)
2. Login to Telegram with that account
3. Rejoin all missing channels
4. Use single-session `listener-db.py` (already fixed)

To find missing channels:
```bash
python3 find_missing_channels.py
```

---

## Comparison Matrix

| Option | Complexity | IP Separation | Concurrent | Setup Time |
|--------|-----------|---------------|------------|------------|
| 1. Simple Dual | Low | ❌ Same IP | ✅ Yes | 10 min |
| 2. Gluetun VPN | Medium | ✅ Different IPs | ✅ Yes | 30 min |
| 3. Sequential VPN | Low | ✅ Different IPs | ❌ No | 15 min |
| 4. Single + Rejoin | Very Low | N/A | N/A | Variable |

---

## Recommendation

**For production use:** Option 2 (Gluetun VPN)
- Clean IP separation
- Concurrent monitoring
- Dockerized and manageable
- No Telegram rate limit concerns

**For quick testing:** Option 1 (Simple Dual)
- Get it working fast
- See if Telegram complains about same IP
- Upgrade to Option 2 if needed

**If you want simplicity:** Option 4 (Single + Rejoin)
- Use the already-fixed `listener-db.py`
- Just rejoin channels with one account
- No dual-session complexity

---

## Files Reference

- `config-dual.yml` - Configuration for two sessions
- `setup_dual_sessions.py` - Setup helper for both sessions
- `src/listener-dual-session.py` - Main dual-session listener (same IP)
- `src/listener-ukraine-only.py` - Ukraine-only listener (for VPN)
- `src/listener-russia-only.py` - Russia-only listener (for VPN)
- `docker-compose-gluetun.yml` - Docker with Gluetun VPN separation
- `find_missing_channels.py` - Identify which channels you're missing

---

## Getting Mullvad Wireguard Configs

1. Go to https://mullvad.net/account/
2. Click "Wireguard configuration"
3. Select platform: Linux
4. Select country: Sweden, Stockholm (for Ukraine)
5. Download config
6. Extract private key and address from config
7. Repeat for Netherlands, Amsterdam (for Russia)

---

## Troubleshooting

**Both sessions from same IP not working?**
→ Switch to Option 2 (Gluetun VPN)

**Don't want complexity?**
→ Use Option 4 (rejoin channels with one account)

**Want to test first?**
→ Use Option 1 locally, upgrade later

**Mullvad setup too complex?**
→ Use any VPN that supports Docker containers (NordVPN, ProtonVPN, etc.)

---

## Next Steps

1. Choose your option (recommend starting with Option 1 for testing)
2. Run `setup_dual_sessions.py` to create session files
3. Verify channel access for each session
4. Deploy chosen option
5. Monitor logs to ensure both sessions working

Questions? Check the main `CHANGES.md` for more details on the code fixes.
