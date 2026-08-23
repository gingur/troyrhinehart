#!/usr/bin/env node
// Blind A/B pairing for critique. Copies two images into an output directory
// as candidate-A.png / candidate-B.png, with the A/B assignment decided by a
// hash of the two files' CONTENTS — deterministic for a given pair of images,
// but not guessable from the command line or argument order. Writes
// mapping.json ({ A: originalPath, B: originalPath }); a critic should look at
// candidate-A/B first and only open mapping.json after writing a verdict.
//
//   node dev/blindpair.mjs <img1> <img2> <outDir>
'use strict';

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';

const [, , img1, img2, outDir] = process.argv;
if (!img1 || !img2 || !outDir) {
  console.error('usage: node dev/blindpair.mjs <img1> <img2> <outDir>');
  process.exit(1);
}

const p1 = resolve(img1);
const p2 = resolve(img2);
const buf1 = readFileSync(p1);
const buf2 = readFileSync(p2);

// Hash content only, in a fixed (content-sorted) order, and let the parity
// decide the CONTENT-LESSER file's slot — so swapping the CLI argument order
// cannot flip the assignment, and the mapping isn't guessable from the args.
const oneIsLesser = Buffer.compare(buf1, buf2) <= 0;
const lesser = oneIsLesser ? { path: p1, buf: buf1 } : { path: p2, buf: buf2 };
const greater = oneIsLesser ? { path: p2, buf: buf2 } : { path: p1, buf: buf1 };
const digest = createHash('sha256').update(lesser.buf).update(greater.buf).digest();

// Even first byte → content-lesser file is A; odd → it is B.
const lesserIsA = digest[0] % 2 === 0;
const A = lesserIsA ? lesser : greater;
const B = lesserIsA ? greater : lesser;

const dir = resolve(outDir);
mkdirSync(dir, { recursive: true });
writeFileSync(join(dir, 'candidate-A.png'), A.buf);
writeFileSync(join(dir, 'candidate-B.png'), B.buf);
writeFileSync(join(dir, 'mapping.json'), JSON.stringify({ A: A.path, B: B.path }, null, 2) + '\n');

console.log('wrote', join(dir, 'candidate-A.png'));
console.log('wrote', join(dir, 'candidate-B.png'));
console.log('wrote', join(dir, 'mapping.json'), '(read only after your verdict)');
