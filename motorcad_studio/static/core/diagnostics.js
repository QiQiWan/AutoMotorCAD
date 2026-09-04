/** Browser-side runtime diagnostics retained in a bounded ring buffer. */
export class Diagnostics {
  constructor({limit = 250} = {}) {
    this.limit = Math.max(10, Number(limit) || 250);
    this.rows = [];
  }
  record(level, event, detail = {}) {
    const row = {timestamp: new Date().toISOString(), level, event, detail};
    this.rows.push(row);
    if (this.rows.length > this.limit) this.rows.splice(0, this.rows.length - this.limit);
    return row;
  }
  snapshot() {
    const clone = globalThis.structuredClone;
    return this.rows.map(row => ({
      ...row,
      detail: typeof clone === 'function' ? clone(row.detail) : JSON.parse(JSON.stringify(row.detail ?? null)),
    }));
  }
}
