// Shared type contracts for the client-side stealer rule DSL engine.
// JSDoc-only; no runtime. Mirrors development/STEALER_RULE_DSL.md v1.
//
// Parity contract: the Python engine (eyenet/stealer/rules/engine.py)
// MUST produce byte-identical EvalResult.fields for the same (rule, input)
// pair. Golden fixtures in tests/fixtures/stealer_rules/ enforce this.

/**
 * @typedef {'container' | 'content'} Layer
 */

/**
 * @typedef {('folder'|'regex'|'delimiter'|'template'|'json'|'yaml'|'keyvalue'|'keyvalue_ini')} RuleType
 */

/**
 * @typedef {object} FolderMatch
 * @property {'folder'} type
 * @property {string[]} [requires]  - paths that MUST exist (relative)
 * @property {string[]} [forbids]   - paths that MUST NOT exist
 * @property {string[]} [optional]  - presence boosts score
 * @property {number}   [min_score] - required (requires + optional) hit count
 */

/**
 * @typedef {object} RegexMatch
 * @property {'regex'} type
 * @property {string}  pattern
 * @property {boolean} [multiline]
 * @property {boolean} [dotall]
 */

/**
 * @typedef {object} DelimiterMatch
 * @property {'delimiter'} type
 * @property {string} separator
 * @property {number} [min_columns]
 * @property {boolean} [skip_blank]
 * @property {string}  [skip_comment_prefix]
 */

/**
 * @typedef {object} TemplateMatch
 * @property {'template'} type
 * @property {string} template
 * @property {boolean} [multiline]
 */

/**
 * @typedef {object} JsonMatch
 * @property {'json'} type
 * @property {string[]} [requires_keys]
 */

/**
 * @typedef {object} YamlMatch
 * @property {'yaml'} type
 * @property {string[]} [requires_keys]
 */

/**
 * @typedef {object} KeyvalueMatch
 * @property {'keyvalue'} type
 * @property {string} separator
 * @property {boolean} [strip_whitespace]
 * @property {string[]} [requires_keys]
 */

/**
 * @typedef {object} KeyvalueIniMatch
 * @property {'keyvalue_ini'} type
 * @property {string[]} [requires_sections]
 */

/**
 * @typedef {FolderMatch|RegexMatch|DelimiterMatch|TemplateMatch|JsonMatch|YamlMatch|KeyvalueMatch|KeyvalueIniMatch} MatchSpec
 */

/**
 * @typedef {object} ExtractSpec
 * @property {string[]}             [fields]   - regex/template named captures to keep
 * @property {Record<number,string>} [columns] - delimiter column index -> field name
 * @property {Record<string,string>} [paths]   - json/yaml JSONPath-lite -> field
 * @property {Record<string,string>} [keys]    - keyvalue / ini `section.key` -> field
 */

/**
 * @typedef {object} MapSpec
 * @property {string[]} [_drop]
 * @property {Record<string,string>} [rename]  - oldName -> newName (any key not `_drop`)
 */

/**
 * @typedef {object} NormalizeStep
 * @property {('strip_whitespace'|'lowercase'|'uppercase'|'truncate'|'int_from_string'|'replace_re2'|'date_parse')} verb
 * @property {string} field
 * @property {number} [max_len]
 * @property {string} [pattern]
 * @property {string} [replacement]
 * @property {('iso8601'|'rfc2822'|'epoch_seconds')} [format]
 */

/**
 * @typedef {object} RuleSpec
 * @property {string} id
 * @property {number} version
 * @property {Layer}  layer
 * @property {string} family
 * @property {number} priority
 * @property {string} [description]
 * @property {string} [path_glob]   - content layer only; default '**\/*'
 * @property {MatchSpec} match
 * @property {ExtractSpec} [extract]
 * @property {MapSpec} [map]
 * @property {NormalizeStep[]} [normalize]
 */

/**
 * The thing a content rule evaluates against: one file's text + its path
 * relative to the victim folder root.
 * @typedef {object} ContentInput
 * @property {string} path
 * @property {string} text
 */

/**
 * The thing a container rule evaluates against: the set of relative paths
 * found inside the victim folder.
 * @typedef {object} ContainerInput
 * @property {string[]} paths
 */

/**
 * Per-rule evaluation outcome.
 * - container: matched = family verdict
 * - content:   fields = extracted (post map + normalize) dict
 * @typedef {object} EvalResult
 * @property {boolean} matched
 * @property {string}  rule_id
 * @property {Layer}   layer
 * @property {string}  family
 * @property {number}  priority
 * @property {Record<string,string|number>} [fields]
 * @property {string}  [reason]   - set when matched=false, for workbench UX
 */

export {};
