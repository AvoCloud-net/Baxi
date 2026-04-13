# Baxi - Features

## Moderation
Ban, kick, mute and warn members with optional temporary durations, auto-escalation and DM notifications. All actions are logged to a configurable mod-log channel.

## Chat Filter
Three-layer message filtering: SafeText keyword/regex rules, AI-powered content moderation via Qwen2.5 (qwen2.5:3b through Ollama) and real-time phishing URL detection.

## Anti-Spam
Detects and acts on message floods, mention spam and repeated content in real time. Configurable thresholds and automatic mute/kick actions.

## Welcomer
Sends custom join and leave messages with optional banner images, configurable colors and per-server member variables such as username, mention and member count.

## Live Stats Channels
Dedicated voice channels that automatically display live server statistics such as member count, bot count and role counts, refreshed every 10 minutes.

## Livestream Tracker
Polls Twitch, YouTube and TikTok for go-live events and new uploads, then posts embed notifications with viewer counts and optional role pings.

## Global Chat
Cross-server chat rooms that relay messages between participating guilds, backed by 24/7 automated moderation and a shared flagged-user database.

## Temp Voice Channels
When a member joins a designated trigger channel, Baxi creates a private voice channel for them and deletes it automatically once everyone has left.

## Support Tickets
Full member support workflow with configurable staff roles, automatic transcripts and a dashboard log of all open and closed tickets.

## Prism - Trust Scoring
Network-wide behavior analysis that assigns every user a trust score based on violations across all Baxi servers, automatically flagging bad actors.

## Minigames
Two built-in community games: a Counting Game where members count in sequence, and a Flag Quiz. Both include leaderboards and configurable hints.

## Suggestions
Members submit ideas to a dedicated channel; Baxi converts each submission into a formatted embed with Accept and Decline buttons for staff to action.

## Reaction & Button Roles
Self-assignable roles triggered by clicking a button on a panel message, fully set up and managed from the dashboard without any coding.

## Auto-Roles
Automatically assigns one or more configured roles to every new member the moment they join the server.

## Custom Commands
Create server-specific slash commands that respond with plain text or rich embeds, configured entirely through the dashboard.

## Warnings & Auto-Slowmode
Issue formal warnings to members with DM notifications, and let Baxi automatically apply channel slowmode when message activity spikes above a threshold.

## Verification
Button-based member verification panel that grants a configured role on click, keeping bots and raiders out without manual intervention.

## Sticky Messages
Pins a message to the bottom of a channel by automatically re-posting it whenever newer messages push it out of view.

## YouTube Video Alerts
Monitors configured YouTube channels and immediately posts an embed with title, thumbnail and an optional role ping when a new video is uploaded.

## Leveling System
Members earn XP for every message they send, scaling with message length, and level up automatically. Role rewards can be assigned to milestone levels and are configured from the dashboard.
