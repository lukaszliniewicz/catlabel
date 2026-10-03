// Cache immutable data URLs, never image/canvas handles or a user's document.
export class CodeRenderCache {
  private readonly completed = new Map<string, string>();
  private readonly pending = new Map<string, Promise<string>>();
  private bytes = 0;
  private generation = 0;

  constructor(private readonly maxEntries = 128, private readonly maxBytes = 8 * 1024 * 1024) {
    if (!Number.isSafeInteger(maxEntries) || maxEntries < 1 || !Number.isSafeInteger(maxBytes) || maxBytes < 1) {
      throw new Error('Code cache budgets must be positive integers.');
    }
  }

  get retainedBytes(): number { return this.bytes; }
  get entryCount(): number { return this.completed.size; }
  get pendingCount(): number { return this.pending.size; }

  clear(): void {
    this.generation += 1;
    this.completed.clear(); this.pending.clear(); this.bytes = 0;
  }

  getOrCreate(key: string, create: () => Promise<string>): Promise<string> {
    const cached = this.completed.get(key);
    if (cached !== undefined) {
      this.completed.delete(key); this.completed.set(key, cached);
      return Promise.resolve(cached);
    }
    const shared = this.pending.get(key);
    if (shared) return shared;
    // Overflow still renders, but does not retain another pending cache entry.
    if (this.pending.size >= this.maxEntries) return Promise.resolve().then(create);
    const generation = this.generation;
    const promise = Promise.resolve().then(create).then(value => {
      if (generation !== this.generation) return value;
      const cost = 2 * (key.length + value.length);
      if (cost > this.maxBytes) return value;
      while (this.completed.size >= this.maxEntries || this.bytes + cost > this.maxBytes) {
        const oldest = this.completed.entries().next().value;
        if (!oldest) break;
        this.completed.delete(oldest[0]); this.bytes -= 2 * (oldest[0].length + oldest[1].length);
      }
      this.completed.set(key, value); this.bytes += cost;
      return value;
    }).finally(() => { if (this.pending.get(key) === promise) this.pending.delete(key); });
    this.pending.set(key, promise);
    return promise;
  }
}
