# Minecraft Server Monitor

![Banner](https://img.shields.io/badge/Minecraft-Monitor-green?style=for-the-badge&logo=minecraft)

![Minecrafts](https://i.imgur.com/UZbjtiy.png)

A lightweight **Minecraft server monitoring tool** written in Python with a **Rich UI**.  
It pings servers using the native Minecraft status protocol (1.7+) and reports changes (MOTD, player count, version, online/offline) to both your terminal and an optional Discord webhook.

---

## Features

-  Rich UI banner, tables, and colored status logs.
-  Monitors:
  - Online/offline state
  - MOTD (color codes stripped)
  - Player count (online/max)
  - Version (name + protocol)
  - Supports `ip:port` and `[IPv6]:port`.
  - Configurable check interval.
  - Discord webhook integration (embeds with before/after state).
  - State persistence: only fires alerts on real changes.
  - Verbose heartbeat mode (`[OK] ... no change`) toggle.

---
