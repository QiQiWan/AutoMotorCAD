/** Fetch client with correlation IDs, cancellation, bounded retries and idempotent writes. */
const randomId = prefix => {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${id}`;
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export class ApiError extends Error {
  constructor(message, {status = 0, code = '', payload = null, url = '', correlationId = ''} = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
    this.url = url;
    this.correlationId = correlationId;
  }
}

export class ApiClient {
  constructor({baseUrl = '', timeoutMs = 30000, bus = null} = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.timeoutMs = timeoutMs;
    this.bus = bus;
    this.etags = new Map();
  }

  clearCache(path = null) {
    if (path == null) this.etags.clear();
    else this.etags.delete(`${this.baseUrl}${String(path).startsWith('/') ? path : `/${path}`}`);
  }

  async request(path, options = {}) {
    const {
      json,
      retries = 2,
      timeoutMs = this.timeoutMs,
      useEtag = false,
      idempotencyKey,
      correlationId: suppliedCorrelationId,
      responseType = 'auto',
      signal: externalSignal,
      ...requestInit
    } = options;
    const method = String(requestInit.method || 'GET').toUpperCase();
    const url = `${this.baseUrl}${String(path).startsWith('/') ? path : `/${path}`}`;
    const correlationId = suppliedCorrelationId || randomId('mcs');
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      const reason = globalThis.DOMException
        ? new DOMException('Request timeout', 'TimeoutError')
        : new Error('Request timeout');
      controller.abort(reason);
    }, Math.max(1, Number(timeoutMs)));
    const relayAbort = () => {
      const reason = externalSignal?.reason || (globalThis.DOMException
        ? new DOMException('Request cancelled', 'AbortError')
        : new Error('Request cancelled'));
      controller.abort(reason);
    };
    externalSignal?.addEventListener?.('abort', relayAbort, {once: true});

    const headers = new Headers(requestInit.headers || {});
    headers.set('X-Correlation-ID', correlationId);
    if (json !== undefined) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !headers.has('Idempotency-Key')) {
      headers.set('Idempotency-Key', idempotencyKey || randomId('cmd'));
    }
    if (method === 'GET' && useEtag && this.etags.has(url)) {
      headers.set('If-None-Match', this.etags.get(url));
    }

    const safeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    const reusableBody = json !== undefined
      || requestInit.body == null
      || typeof requestInit.body === 'string'
      || (globalThis.ArrayBuffer && requestInit.body instanceof ArrayBuffer)
      || (globalThis.Blob && requestInit.body instanceof Blob);
    const idempotentWrite = !safeMethod && headers.has('Idempotency-Key') && reusableBody;
    const attempts = (safeMethod || idempotentWrite) ? Math.max(1, Number(retries) + 1) : 1;
    let lastError = null;
    try {
      for (let attempt = 1; attempt <= attempts; attempt += 1) {
        try {
          this.bus?.emit('api:request', {url, method, correlationId, attempt});
          const response = await fetch(url, {
            ...requestInit,
            method,
            headers,
            signal: controller.signal,
            body: json !== undefined ? JSON.stringify(json) : requestInit.body,
          });
          if (response.status === 304) {
            return {notModified: true, etag: headers.get('If-None-Match'), correlationId};
          }
          const etag = response.headers.get('ETag');
          if (etag && method === 'GET') this.etags.set(url, etag);

          let payload = null;
          if (response.status !== 204 && method !== 'HEAD') {
            const type = response.headers.get('content-type') || '';
            if (responseType === 'arrayBuffer') payload = await response.arrayBuffer();
            else if (responseType === 'blob') payload = await response.blob();
            else if (responseType === 'text') payload = await response.text();
            else if (type.includes('application/json')) {
              const text = await response.text();
              payload = text ? JSON.parse(text) : null;
            } else payload = await response.text();
          }

          if (!response.ok) {
            const detail = payload?.detail || payload || {};
            throw new ApiError(detail.message || detail.detail || `HTTP ${response.status}`, {
              status: response.status,
              code: detail.code || detail.error_code || '',
              payload,
              url,
              correlationId,
            });
          }
          this.bus?.emit('api:response', {url, method, correlationId, status: response.status});
          return payload;
        } catch (error) {
          lastError = error;
          const retryable = (safeMethod || idempotentWrite)
            && attempt < attempts
            && !controller.signal.aborted
            && (!(error instanceof ApiError) || error.status >= 500 || error.status === 429);
          if (!retryable) throw error;
          const delay = Math.min(1500, 150 * 2 ** (attempt - 1));
          this.bus?.emit('api:retry', {url, method, correlationId, attempt, delay});
          await sleep(delay);
        }
      }
      throw lastError || new Error('Request failed');
    } finally {
      clearTimeout(timeout);
      externalSignal?.removeEventListener?.('abort', relayAbort);
    }
  }

  get(path, options = {}) { return this.request(path, {...options, method: 'GET'}); }
  post(path, json, options = {}) { return this.request(path, {...options, method: 'POST', json}); }
  put(path, json, options = {}) { return this.request(path, {...options, method: 'PUT', json}); }
  patch(path, json, options = {}) { return this.request(path, {...options, method: 'PATCH', json}); }
  delete(path, options = {}) { return this.request(path, {...options, method: 'DELETE'}); }
}
