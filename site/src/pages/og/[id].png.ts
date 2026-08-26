import type { APIContext } from 'astro';

import { renderOgImage } from '../../lib/og-image';
import { loadPublishedSummaries } from '../../lib/summary-loader';
import type { SummaryRecord } from '../../lib/summaries';

export const prerender = true;

interface Props {
  record: SummaryRecord;
}

export async function getStaticPaths() {
  return loadPublishedSummaries().map((record) => ({
    params: { id: record.id },
    props: { record },
  }));
}

export async function GET({ props }: APIContext<Props>): Promise<Response> {
  const png = await renderOgImage(props.record);

  return new Response(new Uint8Array(png), {
    headers: {
      'Cache-Control': 'public, max-age=31536000, immutable',
      'Content-Type': 'image/png',
    },
  });
}
