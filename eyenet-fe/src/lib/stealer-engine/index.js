// Public surface of the stealer rule engine. UI code should import from here.
export { runRules, matchGlob, bulkParse } from './engine.js';
export { applyNormalize } from './normalize.js';
export {
  matchFolder,
  matchRegex,
  matchTemplate,
  matchDelimiter,
  matchJson,
  matchYaml,
  matchKeyvalue,
  matchKeyvalueIni
} from './matchers.js';
