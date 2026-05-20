import pygame
import time
import csv
import os
import statistics

# ── Mixer pre-init (must happen before pygame.init) ───────────────────────────
# Buffer size directly controls latency: smaller = lower latency, higher CPU
# 512 samples @ 48kHz = ~10.7ms theoretical minimum
import sys
BUFFER_SIZES = [256, 512, 1024, 2048]
buffer_index = 1  # kept for the log_latency reference, but won't change
BUFFER_SIZE  = int(sys.argv[1]) if len(sys.argv) > 1 else 512     # start at 512
SAMPLE_RATE    = 48000
CHANNELS_COUNT = 2          # stereo

def init_mixer(buf_size):
    pygame.mixer.quit()
    pygame.mixer.pre_init(frequency=SAMPLE_RATE, size=-16,
                          channels=CHANNELS_COUNT, buffer=buf_size)
    pygame.mixer.init()
    print(f"Mixer init: {SAMPLE_RATE}Hz  buffer={buf_size} samples  "
          f"theoretical latency={round(buf_size/SAMPLE_RATE*1000,2)}ms")

# ── Init ──────────────────────────────────────────────────────────────────────
pygame.init()
screen = pygame.display.set_mode((560, 420))
pygame.display.set_caption("Audio Controller")
font    = pygame.font.SysFont(None, 28)
font_sm = pygame.font.SysFont(None, 21)
font_xs = pygame.font.SysFont(None, 18)

init_mixer(BUFFER_SIZE)

# ── Load sounds ───────────────────────────────────────────────────────────────
sound1 = pygame.mixer.Sound("sounds/loop1.wav")
sound2 = pygame.mixer.Sound("sounds/loop2.wav")
sound3 = pygame.mixer.Sound("sounds/loop3.wav")

SOUNDS = {"sound1": sound1, "sound2": sound2, "sound3": sound3}

# ── Config ────────────────────────────────────────────────────────────────────
FADE_MS = 800

# ── State ─────────────────────────────────────────────────────────────────────
master_volume = 0.5
paused        = False

# Per-sound volumes (independent faders)
sound_volumes = {"sound1": 0.8, "sound2": 0.8, "sound3": 0.8}
selected_sound = "sound1"   # which sound the per-sound vol keys affect

active_channels = {"sound1": None, "sound2": None, "sound3": None}

# ── Latency logging ───────────────────────────────────────────────────────────
# Every keydown action is timed and written to latency_log.csv
# Columns: timestamp, action, latency_ms, buffer_size, jitter_ms
LOG_FILE      = "latency_log.csv"
latency_hist  = []   # rolling history for jitter calculation

def _ensure_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp", "action", "latency_ms", "buffer_size", "jitter_ms"])

def log_latency(action, latency_ms):
    """Record one latency measurement; calculate jitter from recent history."""
    latency_hist.append(latency_ms)
    if len(latency_hist) > 50:          # keep last 50 readings
        latency_hist.pop(0)

    jitter = round(statistics.stdev(latency_hist), 3) if len(latency_hist) > 1 else 0.0

    _ensure_log()
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            round(time.time(), 4),
            action,
            round(latency_ms, 3),
            BUFFER_SIZE,
            jitter,
        ])
    return jitter

# ── Recording state ───────────────────────────────────────────────────────────
recording        = False
recorded_snippet = []
record_start     = 0.0

def log_event(action, data=None):
    if not recording:
        return
    recorded_snippet.append({
        "time":   round(time.time() - record_start, 4),
        "action": action,
        "data":   data or {},
    })
    print(f"  [REC] {action} @ {recorded_snippet[-1]['time']}s")

def start_recording():
    global recording, recorded_snippet, record_start
    recording        = True
    recorded_snippet = []
    record_start     = time.time()
    print(">>> RECORDING started — press R again to stop")

def stop_recording():
    global recording
    recording = False
    dur = round(time.time() - record_start, 3)
    print(f">>> RECORDING stopped — {len(recorded_snippet)} events over {dur}s")
    print("    Press P to replay.")

# ── Replay ────────────────────────────────────────────────────────────────────
def replay_snippet():
    if not recorded_snippet:
        print("Nothing recorded. Press R to start recording.")
        return

    pygame.mixer.fadeout(FADE_MS)
    time.sleep(FADE_MS / 1000)
    active_channels.update({k: None for k in active_channels})

    print(f">>> REPLAYING {len(recorded_snippet)} events...")
    replay_start = time.time()
    dev_log = []

    for ev in recorded_snippet:
        while (time.time() - replay_start) < ev["time"]:
            pass
        actual = time.time() - replay_start
        dev_ms = round((actual - ev["time"]) * 1000, 2)
        dev_log.append(dev_ms)
        _execute_event(ev)
        print(f"  [{actual:.3f}s] {ev['action']}  deviation={dev_ms}ms")

    avg = round(sum(dev_log) / len(dev_log), 2)
    mx  = round(max(dev_log), 2)
    jit = round(statistics.stdev(dev_log), 3) if len(dev_log) > 1 else 0.0
    print(f">>> REPLAY done — avg dev: {avg}ms  max: {mx}ms  jitter: {jit}ms")

def _execute_event(ev):
    global master_volume
    action = ev["action"]
    data   = ev["data"]

    if action == "toggle_on":
        key = data["sound"]
        ch  = SOUNDS[key].play(loops=-1, fade_ms=FADE_MS)
        ch.set_volume(data["svol"] * data["mvol"])
        active_channels[key] = ch

    elif action == "toggle_off":
        key = data["sound"]
        if active_channels[key]:
            active_channels[key].fadeout(FADE_MS)
            active_channels[key] = None

    elif action == "sync_start":
        pygame.mixer.fadeout(FADE_MS)
        active_channels.update({k: None for k in active_channels})
        ch1 = sound1.play(loops=-1, fade_ms=FADE_MS)
        ch2 = sound2.play(loops=-1, fade_ms=FADE_MS)
        vol = data["mvol"]
        ch1.set_volume(sound_volumes["sound1"] * vol)
        ch2.set_volume(sound_volumes["sound2"] * vol)
        active_channels["sound1"] = ch1
        active_channels["sound2"] = ch2

    elif action == "stop_all":
        pygame.mixer.fadeout(FADE_MS)
        active_channels.update({k: None for k in active_channels})

    elif action == "master_volume":
        master_volume = data["volume"]
        _apply_all_volumes()

    elif action == "sound_volume":
        sound_volumes[data["sound"]] = data["volume"]
        _apply_sound_volume(data["sound"])

    elif action == "pause":
        pygame.mixer.pause()

    elif action == "unpause":
        pygame.mixer.unpause()

# ── Volume helpers ────────────────────────────────────────────────────────────
def _apply_all_volumes():
    for key, ch in active_channels.items():
        if ch:
            ch.set_volume(sound_volumes[key] * master_volume)

def _apply_sound_volume(key):
    ch = active_channels[key]
    if ch:
        ch.set_volume(sound_volumes[key] * master_volume)

# ── Draw UI ───────────────────────────────────────────────────────────────────
def draw_ui():
    BLACK  = (10,  10,  10)
    WHITE  = (240, 240, 240)
    GREEN  = (80,  200, 80)
    RED    = (220, 60,  60)
    ORANGE = (230, 140, 30)
    GRAY   = (110, 110, 110)
    DIM    = (45,  45,  45)
    BLUE   = (80,  140, 220)
    YELLOW = (220, 200, 60)

    screen.fill(BLACK)

    # ── Title ─────────────────────────────────────────────────────────────────
    screen.blit(font.render("Audio Controller", True, WHITE), (16, 12))

    # ── Buffer size indicator ─────────────────────────────────────────────────
    th = round(BUFFER_SIZE / SAMPLE_RATE * 1000, 1)
    buf_txt = font_xs.render(
        f"Buffer: {BUFFER_SIZE} samples  (~{th}ms)  session fixed", True, BLUE)

    # ── Latency stats ─────────────────────────────────────────────────────────
    if latency_hist:
        avg_l = round(sum(latency_hist) / len(latency_hist), 2)
        jit_l = round(statistics.stdev(latency_hist), 2) if len(latency_hist) > 1 else 0.0
        lat_txt = font_xs.render(
            f"Avg latency: {avg_l}ms   Jitter: {jit_l}ms   ({len(latency_hist)} samples)",
            True, YELLOW)
        screen.blit(lat_txt, (16, 52))

    # ── REC indicator ─────────────────────────────────────────────────────────
    if recording:
        dot = RED if int(time.time() * 2) % 2 == 0 else ORANGE
        pygame.draw.circle(screen, dot, (530, 24), 10)
        screen.blit(font_sm.render("REC", True, dot), (502, 16))

    snip = f"Snippet: {len(recorded_snippet)} events" if recorded_snippet else "Snippet: empty"
    screen.blit(font_xs.render(snip, True, GRAY), (16, 68))

    # ── Sound toggles + per-sound volume bars ─────────────────────────────────
    labels = ["sound1 [1]", "sound2 [2]", "sound3 [3]"]
    keys   = ["sound1",     "sound2",     "sound3"]
    for i, (lbl, key) in enumerate(zip(labels, keys)):
        x      = 16 + i * 178
        active = active_channels[key] is not None
        sel    = key == selected_sound
        color  = GREEN if active else DIM
        border = YELLOW if sel else color
        pygame.draw.rect(screen, color,  (x, 88, 160, 36), border_radius=5)
        pygame.draw.rect(screen, border, (x, 88, 160, 36), 2, border_radius=5)
        screen.blit(font_xs.render(lbl + (" ◀" if sel else ""), True, WHITE), (x + 8, 100))

        # Per-sound volume bar
        sv = sound_volumes[key]
        pygame.draw.rect(screen, DIM,   (x, 128, 160, 7), border_radius=3)
        pygame.draw.rect(screen, BLUE,  (x, 128, int(160 * sv), 7), border_radius=3)
        screen.blit(font_xs.render(f"{round(sv*100)}%", True, GRAY), (x, 138))

    # Select sound hint
    screen.blit(font_xs.render("Tab = select sound   +/- = per-sound vol", True, GRAY), (16, 155))

    # ── Master volume bar ─────────────────────────────────────────────────────
    screen.blit(font_sm.render(f"Master vol: {round(master_volume*100)}%", True, WHITE), (16, 174))
    pygame.draw.rect(screen, DIM,   (16, 194, 300, 10), border_radius=4)
    pygame.draw.rect(screen, GREEN, (16, 194, int(300 * master_volume), 10), border_radius=4)

    # ── Paused ────────────────────────────────────────────────────────────────
    if paused:
        screen.blit(font.render("⏸  PAUSED", True, ORANGE), (16, 210))

    # ── Legend ────────────────────────────────────────────────────────────────
    legend = [
        "1/2/3    toggle sounds (fade in/out)",
        "UP/DN    master volume",
        "Tab      select sound for per-vol",
        "+/-      per-sound volume ±10%",
        "L        sync loops (sound1+2)",
        "S        stop all   SPACE pause/play",
        "R        start/stop recording",
        "P        replay snippet",
        "Q        quit",
    ]
    for i, line in enumerate(legend):
        screen.blit(font_xs.render(line, True, GRAY), (16, 238 + i * 18))

    pygame.display.flip()

# ── Main loop ─────────────────────────────────────────────────────────────────
_ensure_log()
print(f"Latency measurements will be saved to: {os.path.abspath(LOG_FILE)}")
print("Controls: 1/2/3=toggle  UP/DN=master vol  Tab=select  +/-=per-vol")
print("          L=sync  S=stop  SPACE=pause  R=record  P=replay  [/]=buffer  Q=quit")

clock   = pygame.time.Clock()
running = True

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            t0     = time.time()
            action = None

            # ── Toggle sounds ─────────────────────────────────────────────────
            if event.key == pygame.K_1:
                action = "toggle_sound1"
                if active_channels["sound1"] is None:
                    ch = sound1.play(loops=-1, fade_ms=FADE_MS)
                    ch.set_volume(sound_volumes["sound1"] * master_volume)
                    active_channels["sound1"] = ch
                    log_event("toggle_on", {"sound": "sound1",
                               "svol": sound_volumes["sound1"], "mvol": master_volume})
                    print("sound1 ON")
                else:
                    active_channels["sound1"].fadeout(FADE_MS)
                    active_channels["sound1"] = None
                    log_event("toggle_off", {"sound": "sound1"})
                    print("sound1 OFF")

            elif event.key == pygame.K_2:
                action = "toggle_sound2"
                if active_channels["sound2"] is None:
                    ch = sound2.play(loops=-1, fade_ms=FADE_MS)
                    ch.set_volume(sound_volumes["sound2"] * master_volume)
                    active_channels["sound2"] = ch
                    log_event("toggle_on", {"sound": "sound2",
                               "svol": sound_volumes["sound2"], "mvol": master_volume})
                    print("sound2 ON")
                else:
                    active_channels["sound2"].fadeout(FADE_MS)
                    active_channels["sound2"] = None
                    log_event("toggle_off", {"sound": "sound2"})
                    print("sound2 OFF")

            elif event.key == pygame.K_3:
                action = "toggle_sound3"
                if active_channels["sound3"] is None:
                    ch = sound3.play(loops=-1, fade_ms=FADE_MS)
                    ch.set_volume(sound_volumes["sound3"] * master_volume)
                    active_channels["sound3"] = ch
                    log_event("toggle_on", {"sound": "sound3",
                               "svol": sound_volumes["sound3"], "mvol": master_volume})
                    print("sound3 ON")
                else:
                    active_channels["sound3"].fadeout(FADE_MS)
                    active_channels["sound3"] = None
                    log_event("toggle_off", {"sound": "sound3"})
                    print("sound3 OFF")

            # ── Sync loops ────────────────────────────────────────────────────
            elif event.key == pygame.K_l:
                action = "sync_start"
                pygame.mixer.fadeout(FADE_MS)
                active_channels.update({k: None for k in active_channels})
                ch1 = sound1.play(loops=-1, fade_ms=FADE_MS)
                ch2 = sound2.play(loops=-1, fade_ms=FADE_MS)
                ch1.set_volume(sound_volumes["sound1"] * master_volume)
                ch2.set_volume(sound_volumes["sound2"] * master_volume)
                active_channels["sound1"] = ch1
                active_channels["sound2"] = ch2
                log_event("sync_start", {"mvol": master_volume})
                print("Sync loops started")

            # ── Stop all ──────────────────────────────────────────────────────
            elif event.key == pygame.K_s:
                action = "stop_all"
                pygame.mixer.fadeout(FADE_MS)
                active_channels.update({k: None for k in active_channels})
                log_event("stop_all")
                print("All sounds stopping...")

            # ── Master volume ─────────────────────────────────────────────────
            elif event.key == pygame.K_UP:
                action = "master_vol_up"
                master_volume = min(round(master_volume + 0.1, 1), 1.0)
                _apply_all_volumes()
                log_event("master_volume", {"volume": master_volume})
                print(f"Master volume: {round(master_volume*100)}%")

            elif event.key == pygame.K_DOWN:
                action = "master_vol_down"
                master_volume = max(round(master_volume - 0.1, 1), 0.0)
                _apply_all_volumes()
                log_event("master_volume", {"volume": master_volume})
                print(f"Master volume: {round(master_volume*100)}%")

            # ── Select sound (Tab cycles through sound1/2/3) ──────────────────
            elif event.key == pygame.K_TAB:
                keys_list = ["sound1", "sound2", "sound3"]
                selected_sound = keys_list[
                    (keys_list.index(selected_sound) + 1) % 3]
                print(f"Selected: {selected_sound}")

            # ── Per-sound volume ──────────────────────────────────────────────
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                action = f"svol_up_{selected_sound}"
                sound_volumes[selected_sound] = min(
                    round(sound_volumes[selected_sound] + 0.1, 1), 1.0)
                _apply_sound_volume(selected_sound)
                log_event("sound_volume", {"sound": selected_sound,
                           "volume": sound_volumes[selected_sound]})
                print(f"{selected_sound} vol: {round(sound_volumes[selected_sound]*100)}%")

            elif event.key == pygame.K_MINUS:
                action = f"svol_dn_{selected_sound}"
                sound_volumes[selected_sound] = max(
                    round(sound_volumes[selected_sound] - 0.1, 1), 0.0)
                _apply_sound_volume(selected_sound)
                log_event("sound_volume", {"sound": selected_sound,
                           "volume": sound_volumes[selected_sound]})
                print(f"{selected_sound} vol: {round(sound_volumes[selected_sound]*100)}%")

            # ── Pause / play ──────────────────────────────────────────────────
            elif event.key == pygame.K_SPACE:
                action = "pause_toggle"
                if paused:
                    pygame.mixer.unpause()
                    paused = False
                    log_event("unpause")
                    print("UNPAUSED")
                else:
                    pygame.mixer.pause()
                    paused = True
                    log_event("pause")
                    print("PAUSED")

            # ── Record ────────────────────────────────────────────────────────
            elif event.key == pygame.K_r:
                if not recording:
                    start_recording()
                else:
                    stop_recording()

            # ── Replay ────────────────────────────────────────────────────────
            elif event.key == pygame.K_p:
                replay_snippet()

            # ── Quit ──────────────────────────────────────────────────────────
            elif event.key == pygame.K_q:
                running = False

            # ── Log latency for every keyed action ────────────────────────────
            latency_ms = (time.time() - t0) * 1000
            if action:
                jitter = log_latency(action, latency_ms)
                print(f"  latency={round(latency_ms,3)}ms  jitter={jitter}ms  "
                      f"buf={BUFFER_SIZES[buffer_index]}")

    draw_ui()
    clock.tick(60)

pygame.quit()
print(f"\nSession complete. Latency log saved to: {os.path.abspath(LOG_FILE)}")