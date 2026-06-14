"""Round-trip fidelity harness for the SQLite storage migration.

For every `sys`, save a realistic non-default fixture via the new facade, read it
back, and assert byte-identical JSON (key-order tolerant, type-strict: bool!=int,
"0"!=0). Uses a throwaway DB; never touches real data/ or baxi_data.db.

Run:  python test_roundtrip.py
Exit non-zero on any mismatch.
"""
import os
import sys
import json
import copy
import tempfile
import datetime

# Point the DB layer at a throwaway file BEFORE importing anything that connects.
_TMP_DB = tempfile.mktemp(prefix="baxi_rt_", suffix=".db")
os.environ["BAXI_DB_PATH"] = _TMP_DB

import config.config as config
import assets.db as db
db.init(_TMP_DB)
import assets.data as datasys

_DD = config.datasys.default_data
NOW = datetime.datetime.utcnow().isoformat()
TODAY = datetime.datetime.utcnow().strftime("%Y-%m-%d")

GID = 999999


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=True)


def eq(a, b):
    return canon(a) == canon(b)


# ── Fixtures: config systems (realistic, non-default) ──────────────────────────

CONF = {
    "chatfilter": {"enabled": True, "system": "AI", "phishing_filter": True,
                   "warn_on_violation": True,
                   "ai_categories": {"1": False, "2": True, "3": False, "4": True, "5": True}},
    "ticket": {"enabled": True, "channel": "111", "transcript": "222", "catid": "333",
               "role": "444", "color": "#123456", "message": "hi",
               "channel_name_template": "{button}-{user}", "panel_message_id": "555",
               "buttons": [{"id": "support", "label": "Support", "emoji": "🛠️", "style": "primary"},
                           {"id": "bug", "label": "Bug", "emoji": "🐛", "style": "danger"}]},
    "serverlog": {"enabled": True, "channel": "999",
                  "events": {**_DD["serverlog"]["events"], "message_edit": False,
                             "voice_move": False, "role_update": False}},
    "warn_config": {"enabled": True, "expiry_days": 30,
                    "steps": [{"warns": 3, "action": "timeout", "duration": 600, "dm": True},
                              {"warns": 5, "action": "kick", "duration": 0, "dm": False}]},
    "antispam": {"enabled": True, "max_messages": 7, "interval": 4, "max_duplicates": 2,
                 "duplicate_window": 30, "action": "ban",
                 "whitelisted_channels": ["1", "2"], "whitelisted_roles": ["3"]},
    "welcomer": {"enabled": True, "channel": "123", "message": "hey {user}",
                 "leave_enabled": True, "leave_channel": "456", "leave_message": "bye",
                 "color": "#ffffff", "image_mode": "card", "card_color": "#000000",
                 "has_custom_bg": True, "leave_color": "#aaaaaa"},
    "livestream": {"enabled": True, "category_id": "777",
                   "streamers": [{"platform": "twitch", "login": "x", "display_name": "X",
                                  "channel_id": "1", "message_id": "2", "profile_image_url": "u"}]},
    "youtube_videos": {"enabled": True, "alert_channel": "1", "ping_role": "2",
                       "channels": [{"channel_id": "UC123", "display_name": "Chan",
                                     "last_video_id": "v1", "alert_channel": "1"}]},
    "tiktok": {"enabled": True, "alert_channel": "1", "ping_role": "2",
               "channels": [{"username": "u", "display_name": "U", "last_video_id": "v",
                             "alert_channel": ""}]},
    "twitter": {"enabled": True, "alert_channel": "1", "ping_role": "2",
                "channels": [{"username": "nasa", "display_name": "NASA", "profile_image_url": "u",
                              "last_post_id": "99", "last_post_published": "2024-01-01T00:00:00+00:00",
                              "alert_channel": "1"}]},
    "instagram": {"enabled": True, "alert_channel": "1", "ping_role": "2",
                  "channels": [{"username": "u", "display_name": "U", "ig_user_id": "123",
                                "token_expires": 123, "alert_reels": True, "last_post_id": "p",
                                "last_reel_id": "r", "profile_image_url": "u", "alert_channel": ""}]},
    "stats_channels": {"enabled": True, "category_id": "1",
                       "stats": {k: {"enabled": True, "channel_id": str(i), "template": f"{k}: {{count}}"}
                                 for i, k in enumerate(["members", "humans", "bots", "channels", "roles"])}},
    "auto_roles": {"enabled": True, "roles": ["1", "2"]},
    "temp_voice": {"enabled": True, "persist_roles": ["1"],
                   "triggers": [{"create_channel_id": "1", "category_id": "2", "name_template": "{user}"}]},
    "verify": {"enabled": True, "rid": 7, "verify_option": 1, "password": "p", "channel": "c",
               "panel_message_id": "m", "title": "T", "description": "d", "color": "#ffffff"},
    "reaction_roles": {"panels": [{"channel_id": "1", "message_id": "2", "title": "T",
                                   "description": "D", "color": "#ffffff", "max_roles": 0,
                                   "entries": [{"emoji": "😀", "role_id": "3", "label": "L"}]}]},
    "auto_slowmode": {"enabled": True, "threshold": 5, "interval": 8, "slowmode_delay": 3, "duration": 60},
    "counting": {"enabled": True, "channel": "1", "current_count": 5, "high_score": 10,
                 "last_user_id": 42, "no_double_count": False, "react_correct": False, "react_wrong": True},
    "flag_quiz": {"enabled": True, "channel": "1", "hint_after_attempts": 2, "next_delay": 5,
                  "points_enabled": False, "scores": {"42": 10, "43": 5}, "recent_flags": ["de", "fr"]},
    "suggestions": {"enabled": True,
                    "channels": [{"id": "1488", "topic": "General Suggestion", "votes_enabled": True},
                                 {"id": "1303", "topic": "Feedback", "votes_enabled": False}],
                    "staff_role": "3", "log_channel": "4",
                    "auto_forward_enabled": True, "auto_forward_channel": "5", "auto_forward_threshold": 7},
    "leveling": {"enabled": True, "announcement": "dm", "announcement_channel": "1",
                 "role_rewards": [{"level": 5, "role_id": "3"}, {"level": 10, "role_id": "4"}]},
    "auto_release": {"enabled": True, "channels": ["1", "2"], "ignore_bots": False},
    "mc_link": {"enabled": True, "api_url": "u", "api_secret": "s", "role_id": "1",
                "announce_channel": "2", "dm_on_link": True, "allow_self_unlink": False,
                "announcement_channel": "3", "dm_announcements": True, "chat_enabled": True,
                "chat_channel": "4", "chat_webhook_url": "w"},
    "music": {"enabled": True, "queue_limit": 30, "default_volume": 80, "max_song_duration": 300,
              "disconnect_timeout": 120, "allowed_sources": ["youtube", "radio"],
              "radio_whitelist": ["r1"], "allow_all_radios": True, "radio_247_enabled": True,
              "radio_247_channel_id": "1", "radio_247_text_channel_id": "2", "radio_247_url": "u"},
    "donations": {"enabled": True, "provider": "paypal", "stripe_secret_key": "enc:abc",
                  "stripe_webhook_secret": "enc:def", "paypal_client_id": "pid",
                  "paypal_client_secret": "enc:ghi", "page_text": "p", "success_text": "s",
                  "log_enabled": True, "log_channel": "1",
                  "tiers": [{"id": "t1", "name": "Gold", "amount": 5, "role_id": "9"}]},
}

# Scalars (saved individually via save_data)
SCALARS = {"lang": "de", "guild_name": "Test Guild", "guild_id": GID, "owner_id": 42,
           "owner_name": "Owner", "terms": True, "prism_enabled": False,
           "notification_channel": "12345"}

# ── Fixtures: runtime / standalone per-guild stores ────────────────────────────

STORES = {
    "warnings": {"42": [{"id": "a1", "reason": "spam", "mod": "Mod", "mod_id": 7, "date": "2024-01-01"}],
                 "43": [{"id": "b2", "reason": "x", "mod": "M", "mod_id": 8, "date": "2024-02-02"}]},
    "custom_commands": {"hello": {"response": "hi"}, "bye": {"response": "cya"}},
    "giveaways": {"1001": {"channel_id": "1", "reward": "Nitro", "winner_count": 1, "end_time": 123,
                           "host_id": 7, "participants": [1, 2], "ended": False,
                           "image_url": "u", "winner_message": "w"}},
    "polls": {"2002": {"question": "Q", "answers": ["a", "b"], "show_votes": True, "image_url": "",
                       "channel_id": "1", "end_time": 1.5, "user_votes": {"7": 0}, "closed": False}},
    "suggestion_votes": {"s1": {"up": ["1"], "down": ["2"]}},
    "flag_quiz_active": {"channel": "1", "answer": "de"},
    "audit_log": [{"type": "save", "user": "x", "success": True, "time": "01.01.2024 - 00:00", "sys": "welcomer"}],
    "sticky_messages": {"123": {"message": "hi", "last_message_id": "456"}},
    "open_tickets": {"chan1": {"user": 7, "supporterid": 8, "created_at": 123, "status": "open",
                              "title": "T", "message": "M", "button_id": "support",
                              "transcript": [{"a": "b"}]}},
    "transcripts": {"t1": {"messages": [], "closed_by": "x"}},
    "users": {"42": {"id": "42", "name": "X", "flagged": True, "reason": "r", "entry_date": "d",
                     "auto_flagged": False}},
    "stats": {"prossesed_messages": 5, "guild_count": 2, "user_count": 10, "top_servers": {"1": 3}},
    "chatfilter_log": {"log1": {"msg": "x", "false_positive": False, "feedback": {}}},
    "globalchat_message_data": {"gc1": {"author_id": 7, "author_name": "X", "reply": False,
                                        "referenceid": "", "messages": [], "replies": []},
                                "gc2": {"replies": []}},
    "activity": {"msg_by_day": {TODAY: {"total": 5, "by_channel": {"1": {"name": "gen", "count": 5}},
                                        "by_user": {"7": {"name": "u", "count": 5}}, "by_hour": {"3": 5}}},
                 "member_by_day": {TODAY: {"joins": 2, "leaves": 1}}},
    "leveling_users": {"7": {"xp": 100, "level": 2, "messages": 50, "name": "U"},
                       "8": {"xp": 5, "level": 0, "messages": 3, "name": "V"}},
    "mod_events": [{"type": "ban", "user_id": "7", "user_name": "U", "mod_id": "8", "mod_name": "M",
                    "reason": "r", "timestamp": NOW}],
    "filter_events": [{"type": "filter", "timestamp": NOW, "detail": "x"}],
}

# ── Fixtures: 1001 global bag (tested with sid=1001) ───────────────────────────

BAG = {
    "admins": [111, 222],  # Discord IDs are ints (user.id in admins comparison)
    "ba_ban": {"7": {"reason": "x", "date": "d"}},
    "gc_ban": {"8": {"reason": "y"}},
    "globalchat": {str(GID): {"enabled": True, "channel": "1"}},
    "updates": {str(GID): {"cid": "2"}},
    "feature_access": {"music": {"mode": "whitelist", "guilds": ["1"]}},
}


class FakeBot:
    def get_guild(self, gid):
        return None


def main():
    results = []  # (label, ok, detail)

    def check(label, saved):
        sysname = label
        datasys.save_data(GID, sysname, copy.deepcopy(saved))
        got = datasys.load_data(GID, sysname)
        ok = eq(saved, got)
        results.append((label, ok, None if ok else f"\n  saved={canon(saved)}\n  got  ={canon(got)}"))

    # Config systems
    for k, v in CONF.items():
        check(k, v)

    # Scalars
    for k, v in SCALARS.items():
        check(k, v)

    # Stores
    for k, v in STORES.items():
        check(k, v)

    # temp_actions via its dedicated API (not load_data/save_data)
    ta = {"bans": [{"user_id": "7", "expires_at": NOW}],
          "timeouts": [{"user_id": "8", "expires_at": NOW}]}
    datasys.save_temp_actions(GID, copy.deepcopy(ta))
    got_ta = datasys.load_temp_actions(GID)
    results.append(("temp_actions", eq(ta, got_ta),
                    None if eq(ta, got_ta) else f"\n  saved={canon(ta)}\n  got  ={canon(got_ta)}"))

    # 1001 bag (sid=1001)
    for k, v in BAG.items():
        datasys.save_data(1001, k, copy.deepcopy(v))
        got = datasys.load_data(1001, k)
        ok = eq(v, got)
        results.append((f"1001:{k}", ok, None if ok else f"\n  saved={canon(v)}\n  got  ={canon(got)}"))

    # "all" aggregation: every conf system + scalars must appear with saved values
    alld = datasys.load_data(GID, "all", bot=FakeBot())
    all_ok = True
    all_detail = []
    for k, v in {**CONF, **SCALARS}.items():
        if k not in alld:
            all_ok = False; all_detail.append(f"missing key {k}")
        elif not eq(v, alld[k]):
            all_ok = False; all_detail.append(f"{k}: {canon(v)} != {canon(alld.get(k))}")
    # guild_info keys present
    for k in ["name", "id", "icon_url", "member_count", "dash_login"]:
        if k not in alld:
            all_ok = False; all_detail.append(f"missing guild_info key {k}")
    results.append(("all", all_ok, None if all_ok else "\n  " + "\n  ".join(all_detail)))

    # Report
    fails = [r for r in results if not r[1]]
    for label, ok, detail in results:
        if not ok:
            print(f"FAIL  {label}{detail}")
    passed = len(results) - len(fails)
    print(f"\n{passed}/{len(results)} passed, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    code = main()
    try:
        os.remove(_TMP_DB)
        for ext in ("-wal", "-shm"):
            if os.path.exists(_TMP_DB + ext):
                os.remove(_TMP_DB + ext)
    except OSError:
        pass
    sys.exit(code)
