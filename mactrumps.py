#!/usr/bin/env python3
"""Make a Top Trumps card prompt from your Mac's app-usage log (knowledgeC.db).

usage:  python3 mactrumps.py [--name "THE 9PM COMPILER"] [--json] [path/to/knowledgeC.db]

Paste the output into ChatGPT (image generation) to get the card.
Needs Full Disk Access for your terminal app: System Settings > Privacy & Security.
"""
import json, os, re, shutil, sqlite3, sys, tempfile

DEFAULT_DB = os.path.expanduser("~/Library/Application Support/Knowledge/knowledgeC.db")

SQL = """
with u as (
  select ZVALUESTRING app, ZSTARTDATE st, ZENDDATE en, ZENDDATE-ZSTARTDATE dur,
    cast(strftime('%H',ZSTARTDATE+978307200,'unixepoch','localtime') as int) hr,
    date(ZSTARTDATE+978307200,'unixepoch','localtime') d
  from ZOBJECT where ZSTREAMNAME='/app/usage' and ZENDDATE>ZSTARTDATE),
sw as (select app a, lead(app) over (order by st) b, lead(st) over (order by st)-en gap from u),
msg as (select sum(dur) s from u where app like '%whatsapp%' or app like '%signal%' or app like '%telegram%'
        or app like '%slack%' or app like '%discord%' or app like '%messages%')
select json_object(
 'from',(select min(d) from u), 'to',(select max(d) from u), 'active_days',(select count(distinct d) from u),
 'total_hours',(select round(sum(dur)/3600.0,1) from u),
 'hours_per_active_day',(select round(sum(dur)/3600.0/count(distinct d),1) from u),
 'after_8pm_pct',(select round(100*sum(case when hr>=20 then dur end)/sum(dur)) from u),
 'peak_hour',(select hr from u group by hr order by sum(dur) desc limit 1),
 'switches_per_hour',(select round(count(*)/(sum(dur)/3600.0)) from u),
 'median_session_sec',(select dur from u order by dur limit 1 offset (select count(*)/2 from u)),
 'longest_app',(select app from u order by dur desc limit 1),
 'longest_minutes',(select round(dur/60.0) from u order by dur desc limit 1),
 'distinct_apps',(select count(distinct app) from u),
 'messaging_pct',(select round(100*s/(select sum(dur) from u)) from msg),
 'top_apps',(select json_group_array(json_object('app',app,'hours',h)) from
   (select app, round(sum(dur)/3600.0,1) h from u group by app order by h desc limit 8)),
 'top_transition',(select json_object('a',a,'b',b,'n',c) from
   (select a,b,count(*) c from sw where a!=b and gap<5 group by 1,2 order by c desc limit 1)),
 'rare_apps',(select json_group_array(app) from (select app from u group by app having count(*)<=5)),
 'top_notification',(select json_object('app',b,'n',c) from
   (select m.Z_DKNOTIFICATIONUSAGEMETADATAKEY__BUNDLEID b, count(*) c from ZOBJECT o
    join ZSTRUCTUREDMETADATA m on o.ZSTRUCTUREDMETADATA=m.Z_PK
    where o.ZSTREAMNAME='/notification/usage' group by 1 order by c desc limit 1)),
 'beta_os_builds',(select count(distinct Z_DKDISCOVERABILITYSIGNALSMETADATAKEY__OSBUILD)
   from ZSTRUCTUREDMETADATA where Z_DKDISCOVERABILITYSIGNALSMETADATAKEY__OSBUILD glob '*[a-z]')
)"""


def load(db):
    tmp = os.path.join(tempfile.mkdtemp(), "k.db")
    try:
        shutil.copy(db, tmp)  # the live db is locked and TCC-protected
    except PermissionError:
        sys.exit("Can't read knowledgeC.db. Give your terminal Full Disk Access "
                 "(System Settings > Privacy & Security > Full Disk Access), restart it, retry.")
    row = sqlite3.connect(tmp).execute(SQL).fetchone()[0]
    d = json.loads(row)
    for k in ("top_transition", "top_notification"):  # sqlite returns nested json as text
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


NAMES = {"VSCode": "VS Code", "SoftwareUpdateNotification": "Software Update", "utweb": "uTorrent",
         "drivefs": "Google Drive", "optionsplus": "Logi Options+", "crealityprint": "Creality Print"}


def app(bundle):  # com.microsoft.VSCode -> VS Code, com.brave.Browser -> Brave
    parts = bundle.split(".")
    last = re.sub(r"[_-].*", "", parts[-1])
    name = parts[-2] if last in ("App", "Electron", "Browser", "chat") else last
    return NAMES.get(name) or name[0].upper() + name[1:]  # brave -> Brave, MeshInspector stays


def stats(d):
    cap = lambda x: int(min(100, max(0, round(x))))
    return {
        "NIGHT OWL":     cap(d["after_8pm_pct"] * 2),          # 50% after 8pm = 100
        "TWITCH":        cap(100 - d["median_session_sec"]),    # 0s median session = 100
        "DEEP FOCUS":    cap(d["longest_minutes"]),             # 100 min unbroken = 100
        "GRIND":         cap(d["hours_per_active_day"] * 12.5), # 8h/day = 100
        "CHATTER":       cap(d["messaging_pct"] * 5),           # 20% in messaging = 100
        "TOOLBELT":      cap(d["distinct_apps"] * 2),           # 50 apps = 100
        "BLEEDING EDGE": cap(d["beta_os_builds"] * 25),         # 4 beta builds = 100
    }


def prompt(d, name):
    s = stats(d)
    top = app(d["top_apps"][0]["app"])
    name = name or f"THE {d['peak_hour'] % 12 or 12}{'PM' if d['peak_hour'] >= 12 else 'AM'} {top.upper()}"
    t = d["top_transition"]
    move = f"{app(t['a'])} <-> {app(t['b'])} tab-flip, {t['n']} times"
    n = d["top_notification"]
    weak = f"{app(n['app'])} notification, ignored {n['n']} times" if n else "none recorded"
    loot = ", ".join(app(x) for x in d["rare_apps"] if not x.startswith("com.apple"))[:40].rsplit(", ", 1)[0] or "none"
    hi = max(s.values())
    rarity = "LEGENDARY" if hi == 100 else "RARE" if hi >= 80 else "COMMON"
    rows = "\n".join(f"  {k:<14} {v:>3}" for k, v in s.items())
    return f"""Create a single Top Trumps style trading card, portrait, 2:3 aspect ratio. Retro 1980s British Top Trumps look: thick coloured border, flat bold colours, slight halftone print texture, chunky sans-serif type. Render ALL text below exactly as written, no extra words, no typos.

TOP BANNER (large, uppercase): {name}
SUB-LABEL under the banner (small): {rarity} · {d['from']} to {d['to']}

ILLUSTRATION (upper half): a caricature of a computer user at a desk, {'lit only by monitor glow at night' if s['NIGHT OWL'] >= 60 else 'in bright daylight'}, {top} open on screen, {'dozens of' if s['TOOLBELT'] >= 80 else 'a few'} app icons floating around them. Comic-book style, no photorealism.

STATS PANEL (lower half): 7 rows, each with the stat name on the left, the number on the right, and a horizontal bar filled to that value out of 100:
{rows}

BOTTOM BOX (small type):
  SIGNATURE MOVE: {move}
  WEAKNESS: {weak}
  RARE LOOT: {loot}

Footer (tiny): {d['total_hours']}h foreground · {d['active_days']} active days · {d['switches_per_hour']:.0f} app switches/hour
"""


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args.pop(args.index("--name") + 1) if "--name" in args else None
    if name: args.remove("--name")
    want_json = "--json" in args
    if want_json: args.remove("--json")
    d = load(args[0] if args else DEFAULT_DB)
    print(json.dumps(d, indent=2) if want_json else prompt(d, name))
