// Minimal time-based tweening for camera choreography (no dependency, testable headless).

export const ease = {
  linear: (t: number) => t,
  outCubic: (t: number) => 1 - Math.pow(1 - t, 3),
  inOutCubic: (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  inOutSine: (t: number) => -(Math.cos(Math.PI * t) - 1) / 2,
};

export type Tween = {
  start: number;          // ms, performance.now() clock
  duration: number;       // ms
  easing: (t: number) => number;
  step: (k: number) => void;
  done?: () => void;
};

export class Tweens {
  private list: Tween[] = [];

  add(t: Omit<Tween, 'start'> & { delay?: number }, now: number): Tween {
    const tw: Tween = { ...t, start: now + (t.delay ?? 0) };
    this.list.push(tw);
    return tw;
  }

  /** Advance all tweens; returns true while any is running. */
  update(now: number): boolean {
    if (this.list.length === 0) return false;
    const keep: Tween[] = [];
    for (const tw of this.list) {
      if (now < tw.start) { keep.push(tw); continue; }
      const raw = tw.duration <= 0 ? 1 : Math.min(1, (now - tw.start) / tw.duration);
      tw.step(tw.easing(raw));
      if (raw < 1) keep.push(tw); else tw.done?.();
    }
    this.list = keep;
    return keep.length > 0;
  }

  /** Jump every tween to its end (used when the user skips an animation). */
  finishAll(): void {
    const all = this.list;
    this.list = [];
    for (const tw of all) { tw.step(1); tw.done?.(); }
  }

  get active(): boolean { return this.list.length > 0; }
}
