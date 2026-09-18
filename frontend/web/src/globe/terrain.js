/**
 * Keyless terrain for the 3D globe.
 *
 * Adapted from gods-eye-view `src/maps/terrain.js`
 * (https://github.com/bilawalsidhu/gods-eye-view @ 0d41b6b, MIT — see
 * LICENSE-gods-eye-view). The Cesium-ion `createWorldTerrain` branch is
 * deliberately absent: it cannot work without a token, and a token is exactly
 * what HeatShield refuses to require.
 *
 * Terrain is a luxury, not a dependency. If the keyless terrain service is
 * unreachable the globe degrades to the WGS84 ellipsoid — imagery, ward
 * polygons and zone markers all render exactly as before — and the caller gets
 * an honest message to show on the map instead of a silent downgrade.
 */
import * as Cesium from 'cesium'

/** Re:Earth / Mapterhorn ellipsoidal quantized-mesh, CC BY 4.0. */
export const KEYLESS_TERRAIN_URL = 'https://terrain.reearth.land/cesium-mesh/ellipsoid'

/** Lazily created: a hidden globe must not trigger terrain loading. */
export async function createKeylessTerrain({ signal, onFallback } = {}) {
  signal?.throwIfAborted()
  try {
    const provider = await Cesium.CesiumTerrainProvider.fromUrl(KEYLESS_TERRAIN_URL)
    signal?.throwIfAborted()
    return { provider, fallbackMessage: null, terrainId: 'keyless' }
  } catch (error) {
    console.warn(
      '[HeatShield globe] keyless terrain unavailable, using the smooth ellipsoid:',
      error,
    )
    onFallback?.(
      '3D terrain is unavailable on this network — the globe is flat (smooth ellipsoid). ' +
        'Imagery, ward shapes and risk colours are unaffected.',
    )
    return {
      provider: new Cesium.EllipsoidTerrainProvider(),
      fallbackMessage:
        '3D terrain is unavailable on this network — the globe is flat (smooth ellipsoid). ' +
        'Imagery, ward shapes and risk colours are unaffected.',
      terrainId: 'ellipsoid',
    }
  }
}
