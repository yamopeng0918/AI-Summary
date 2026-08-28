declare module '@shuding/opentype.js' {
  interface OpenTypeFont {
    charToGlyphIndex(character: string): number;
  }

  export function parse(buffer: ArrayBuffer): OpenTypeFont;
}
