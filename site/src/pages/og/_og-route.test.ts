import { describe, expect, it } from 'vitest';
import sharp from 'sharp';

import { GET, getStaticPaths } from './[id].png';

describe('OG PNG route', () => {
  it('creates paths only from the published-summary loader result', async () => {
    const paths = await getStaticPaths();

    expect(paths.length).toBeGreaterThan(0);
    expect(paths.every((path) => typeof path.params.id === 'string')).toBe(true);
  });

  it('returns a valid PNG response for route props', async () => {
    const [{ props }] = await getStaticPaths();
    const response = await GET({ props } as Parameters<typeof GET>[0]);
    const bytes = Buffer.from(await response.arrayBuffer());

    expect(response.headers.get('content-type')).toBe('image/png');
    expect(await sharp(bytes).metadata()).toMatchObject({ format: 'png', width: 1200, height: 630 });
  });
});
