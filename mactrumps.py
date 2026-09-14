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
    night = s["NIGHT OWL"] >= 60
    scene = (f"a caricature of a computer user at a desk, {'lit by monitor glow with a night-time city window behind' if night else 'in a bright daytime room with a sunny window'}, "
             f"two monitors, one showing {top}, the other a web browser, "
             f"{'shelves crammed with gadgets and dozens of app icons and stickers everywhere' if s['TOOLBELT'] >= 80 else 'a tidy desk with a few app icons'}, "
             f"{'headphones round the neck' if d['messaging_pct'] < 15 else 'a phone buzzing with message notifications'}, a coffee mug.")
    border = {"LEGENDARY": "yellow #FFD60A", "RARE": "red #D62828", "COMMON": "navy #1D3557"}[rarity]
    colours = ["blue #1E90FF", "purple #8A2BE2", "green #3CB043", "orange #FF8C00", "yellow #FFD60A", "pink #E63976", "red #E63946"]
    rows = "\n".join(f"  {k:<14} {v:>3}   (bar colour {c})" for (k, v), c in zip(s.items(), colours))
    return f"""Create ONE Top Trumps style trading card as a single image. Follow this style guide exactly so the card matches a set.

FORMAT: portrait, 2:3 aspect ratio, card fills the whole image, rounded corners, flat front-on view, no perspective, no hand holding it, no background scene. Slight worn-print halftone texture over the whole card.

STYLE GUIDE (fixed for every card in the set):
- Border: thick {border} border, about 4% of card width, rounded corners. Every panel inside has a thin black outline.
- Banner: red #D62828 panel across the top, card name in huge condensed heavy sans-serif (Impact-like), yellow #FFD60A fill with black outline.
- Sub-label: cream panel directly under the banner, black condensed caps.
- Card face and text panels: cream #F4E9C8. All body text black, condensed heavy sans-serif for labels, regular sans-serif for values.
- Illustration: detailed comic-book ink-and-colour style, visible linework, rich colour, a full scene not a flat icon. Small readable text on props (mugs, posters, sticky notes) is fine. No logos of real companies except app UI on screens.
- Stats: each row is a rounded bar with a dark grey #333333 track and a black outline, filled from the left in the colour given for that stat, the number in black to the right of the bar.
- No watermarks, no extra decoration, no text other than what is listed below and small prop text in the illustration. Render all listed text exactly as written, no typos.

LAYOUT, top to bottom:
1. BANNER: {name}
2. SUB-LABEL: {rarity} · {d['from']} to {d['to']}
3. ILLUSTRATION, about 40% of card height: {scene}
4. STATS PANEL: 7 rows, stat name on the left, coloured bar in the middle, number on the right:
{rows}
5. BOTTOM BOX: cream rounded rectangle with black outline, three lines, label in bold caps then value:
  SIGNATURE MOVE: {move}
  WEAKNESS: {weak}
  RARE LOOT: {loot}
6. FOOTER: small black text, centred: {d['total_hours']}h foreground · {d['active_days']} active days · {d['switches_per_hour']:.0f} app switches/hour
"""


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args.pop(args.index("--name") + 1) if "--name" in args else None
    if name: args.remove("--name")
    want_json = "--json" in args
    if want_json: args.remove("--json")
    d = load(args[0] if args else DEFAULT_DB)
    print(json.dumps(d, indent=2) if want_json else prompt(d, name))
