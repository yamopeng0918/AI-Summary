import satori from 'satori';
import { createElement, type JSXNode } from 'satori/jsx';
import sharp from 'sharp';

import boldFontDataUrl from '../assets/fonts/NotoSerifTC-Bold.ttf?inline';
import regularFontDataUrl from '../assets/fonts/NotoSerifTC-Regular.ttf?inline';
import type { SummaryRecord } from './summaries';

const fontData = Promise.all([
  fetch(new URL(regularFontDataUrl, import.meta.url)).then(async (response) => {
    return Buffer.from(await response.arrayBuffer());
  }),
  fetch(new URL(boldFontDataUrl, import.meta.url)).then(async (response) => {
    return Buffer.from(await response.arrayBuffer());
  }),
]);

export interface OgImageContent {
  title: string;
  summary: string;
  category: string;
  source: string;
  sourceType: 'WEB' | 'YOUTUBE' | 'SOCIAL';
}

export function fitOgText(text: string, limits: readonly number[]): string[] {
  const characters = Array.from(text.trim());
  const lines: string[] = [];
  let offset = 0;
  for (const limit of limits) {
    if (offset >= characters.length) break;
    const remaining = characters.length - offset;
    const take = Math.min(limit, remaining);
    lines.push(characters.slice(offset, offset + take).join(''));
    offset += take;
  }
  if (offset < characters.length && lines.length > 0) {
    const last = lines.length - 1;
    lines[last] = `${Array.from(lines[last]).slice(0, -1).join('')}…`;
  }
  return lines;
}

export function createOgImageContent(record: SummaryRecord): OgImageContent {
  return {
    title: record.title,
    summary: record.summary,
    category: record.category,
    source: record.author?.trim() || new URL(record.canonicalUrl).hostname,
    sourceType: record.sourceType.toUpperCase() as OgImageContent['sourceType'],
  };
}

export async function renderOgImage(record: SummaryRecord): Promise<Buffer> {
  const content = createOgImageContent(record);
  const titleLines = fitOgText(content.title, [22, 22, 22]);
  const summaryLines = fitOgText(content.summary, [46, 46]);
  const [regularFontData, boldFontData] = await fontData;
  const svg = await satori(
    createElement(
      'div',
      {
        style: {
          backgroundColor: '#f7f2e7',
          color: '#17352d',
          display: 'flex',
          flexDirection: 'column',
          fontFamily: 'Noto Serif TC',
          height: '630px',
          padding: '52px 64px 48px',
          width: '1200px',
        },
      },
      createElement('div', {
        style: { backgroundColor: '#ef6a47', height: '12px', marginBottom: '28px', width: '100%' },
      }) as JSXNode,
      createElement(
        'div',
        { style: { display: 'flex', fontSize: '26px', fontWeight: 700, letterSpacing: '0.12em' } },
        'AI DIGEST',
      ) as JSXNode,
      createElement(
        'div',
        {
          style: {
            display: 'flex',
            flexDirection: 'column',
            fontSize: '54px',
            fontWeight: 700,
            lineHeight: 1.25,
            marginTop: '26px',
          },
        },
        ...titleLines.map(
          (line) => createElement('div', { style: { display: 'flex' } }, line) as JSXNode,
        ),
      ) as JSXNode,
      createElement(
        'div',
        {
          style: {
            display: 'flex',
            flexDirection: 'column',
            fontSize: '25px',
            lineHeight: 1.5,
            marginTop: '24px',
          },
        },
        ...summaryLines.map(
          (line) => createElement('div', { style: { display: 'flex' } }, line) as JSXNode,
        ),
      ) as JSXNode,
      createElement(
        'div',
        {
          style: {
            display: 'flex',
            fontSize: '22px',
            fontWeight: 700,
            marginTop: 'auto',
          },
        },
        `${content.category}  |  ${content.source}  |  ${content.sourceType}`,
      ) as JSXNode,
    ),
    {
      fonts: [
        { data: regularFontData, name: 'Noto Serif TC', weight: 400, style: 'normal' },
        { data: boldFontData, name: 'Noto Serif TC', weight: 700, style: 'normal' },
      ],
      height: 630,
      width: 1200,
    },
  );
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  const metadata = await sharp(png).metadata();
  if (metadata.format !== 'png' || metadata.width !== 1200 || metadata.height !== 630) {
    throw new Error('OG image renderer produced invalid PNG dimensions');
  }
  return png;
}
