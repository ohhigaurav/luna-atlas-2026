// Which ground model an answer used, in words, on every answer (challenge C9b; independent review
// 6 Nov item 4). 5 m and 240 m terrain can disagree (Site 001: 69% vs 100% sunlight in Jan 2027).
export function terrainText(horizonMode: string | undefined, finestM: number | null | undefined): string {
  if (horizonMode && horizonMode !== 'terrain') return 'flat horizon (no terrain map here)';
  if (finestM == null) return 'terrain';
  return `${finestM >= 100 ? Math.round(finestM) : +finestM.toFixed(1)} m terrain`;
}
