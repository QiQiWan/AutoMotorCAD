import {ControlPlaneClient} from './client.js';

/** Install the canonical M5-B/M5-C frontend integration as a scoped feature. */
export function installControlPlaneFeature({namespace, scope}) {
  if (!namespace?.api || !namespace?.features) throw new TypeError('frontend namespace is incomplete');
  const client = new ControlPlaneClient({api: namespace.api, stores: namespace.stores, bus: namespace.bus});
  Object.defineProperty(namespace, 'controlPlane', {
    value: client,
    configurable: false,
    enumerable: true,
    writable: false,
  });

  const unregister = namespace.features.register({
    id: 'control-plane',
    match: () => true,
    mount: async ({scope: featureScope}) => {
      const controller = featureScope.abortController();
      try {
        const runtime = await client.runtime({signal: controller.signal, retries: 1, timeoutMs: 10000});
        namespace.diagnostics?.record?.('INFO', 'CONTROL_PLANE_CONNECTED', {
          authority: runtime?.authority || null,
          schemaVersion: runtime?.schema_version || runtime?.schemaVersion || null,
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        namespace.diagnostics?.record?.('WARNING', 'CONTROL_PLANE_UNAVAILABLE', {
          message: String(error?.message || error),
        });
      }
      featureScope.onBus(namespace.bus, 'control-plane:refresh-requested', async () => {
        try { await client.runtime({signal: controller.signal, retries: 0}); }
        catch (error) {
          if (!controller.signal.aborted) namespace.diagnostics?.record?.('WARNING', 'CONTROL_PLANE_REFRESH_FAILED', {message: String(error?.message || error)});
        }
      });
    },
  });
  scope.defer(unregister);
  return Object.freeze({client, snapshot: () => client.snapshot()});
}
