export function opencodeLaunchCommand(configPath) {
  if (/^(?:[a-z]:\\|\\\\)/i.test(configPath)) {
    return `$env:OPENCODE_CONFIG = '${configPath.replaceAll("'", "''")}'; opencode --standalone`;
  }
  return `OPENCODE_CONFIG='${configPath.replaceAll("'", "'\"'\"'")}' opencode --standalone`;
}
