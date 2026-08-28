import satori from 'satori';
import { createElement, type JSXNode } from 'satori/jsx';
import sharp from 'sharp';
import { parse } from '@shuding/opentype.js';

import boldFontDataUrl from '../assets/fonts/NotoSerifCJKtc-Bold.otf?inline';
import regularFontDataUrl from '../assets/fonts/NotoSerifCJKtc-Regular.otf?inline';
import type { SummaryRecord } from './summaries';

const fontData = Promise.all([
  fetch(new URL(regularFontDataUrl, import.meta.url)).then(async (response) => {
    return Buffer.from(await response.arrayBuffer());
  }),
  fetch(new URL(boldFontDataUrl, import.meta.url)).then(async (response) => {
    return Buffer.from(await response.arrayBuffer());
  }),
]).then(([regularFontData, boldFontData]) => ({
  boldFont: parse(
    boldFontData.buffer.slice(
      boldFontData.byteOffset,
      boldFontData.byteOffset + boldFontData.byteLength,
    ) as ArrayBuffer,
  ),
  boldFontData,
  regularFont: parse(
    regularFontData.buffer.slice(
      regularFontData.byteOffset,
      regularFontData.byteOffset + regularFontData.byteLength,
    ) as ArrayBuffer,
  ),
  regularFontData,
}));

export interface OgImageContent {
  title: string;
  summary: string;
  category: string;
  source: string;
  sourceType: 'WEB' | 'YOUTUBE' | 'SOCIAL';
}

export interface OgImageLayout extends OgImageContent {
  titleLines: string[];
  summaryLines: string[];
}

export interface FontCharacterMap {
  charToGlyphIndex(character: string): number;
}

const TITLE_LINE_LIMITS = [18, 18, 18] as const;
const SUMMARY_LINE_LIMITS = [40, 40] as const;
const SOURCE_LABEL_LIMIT = 36;

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

export function assertFontCoversStrings(
  font: FontCharacterMap,
  strings: readonly string[],
  fontLabel: string,
): void {
  const missingCharacters = [
    ...new Set(strings.flatMap((value) => Array.from(value))),
  ].filter((character) => font.charToGlyphIndex(character) === 0);
  if (missingCharacters.length > 0) {
    throw new Error(`OG font ${fontLabel} is missing glyphs: ${missingCharacters.join(', ')}`);
  }
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

export function createOgImageLayout(record: SummaryRecord): OgImageLayout {
  const content = createOgImageContent(record);
  return {
    ...content,
    titleLines: fitOgText(content.title, TITLE_LINE_LIMITS),
    summaryLines: fitOgText(content.summary, SUMMARY_LINE_LIMITS),
    source: fitOgText(content.source, [SOURCE_LABEL_LIMIT])[0] ?? '',
  };
}

export async function renderOgImage(record: SummaryRecord): Promise<Buffer> {
  const content = createOgImageLayout(record);
  const { boldFont, boldFontData, regularFont, regularFontData } = await fontData;
  assertFontCoversStrings(
    boldFont,
    ['AI DIGEST', content.category, ...content.titleLines, content.source, content.sourceType],
    'Noto Serif CJK TC Bold',
  );
  assertFontCoversStrings(
    regularFont,
    content.summaryLines,
    'Noto Serif CJK TC Regular',
  );
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
        {
          style: {
            alignItems: 'center',
            display: 'flex',
            fontSize: '26px',
            fontWeight: 700,
            justifyContent: 'space-between',
            letterSpacing: '0.12em',
            width: '100%',
          },
        },
        createElement('div', { style: { display: 'flex', whiteSpace: 'nowrap' } }, 'AI DIGEST') as JSXNode,
        createElement(
          'div',
          { style: { display: 'flex', textAlign: 'right', whiteSpace: 'nowrap' } },
          content.category,
        ) as JSXNode,
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
        ...content.titleLines.map(
          (line) =>
            createElement(
              'div',
              { style: { display: 'flex', overflow: 'hidden', whiteSpace: 'nowrap', width: '100%' } },
              line,
            ) as JSXNode,
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
        ...content.summaryLines.map(
          (line) =>
            createElement(
              'div',
              { style: { display: 'flex', overflow: 'hidden', whiteSpace: 'nowrap', width: '100%' } },
              line,
            ) as JSXNode,
        ),
      ) as JSXNode,
      createElement(
        'div',
        {
          style: {
            display: 'flex',
            fontSize: '22px',
            fontWeight: 700,
            justifyContent: 'space-between',
            marginTop: 'auto',
            width: '100%',
          },
        },
        createElement(
          'div',
          { style: { display: 'flex', overflow: 'hidden', whiteSpace: 'nowrap' } },
          content.source,
        ) as JSXNode,
        createElement('div', { style: { display: 'flex', whiteSpace: 'nowrap' } }, content.sourceType) as JSXNode,
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
