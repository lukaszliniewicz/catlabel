import { describe, expect, it } from 'vitest';
import { opencodeLaunchCommand } from './harnessConnection';

describe('OpenCode launch command', () => {
  it('quotes a POSIX path including spaces and apostrophes', () => {
    expect(opencodeLaunchCommand("/home/user/it's a label/config.json"))
      .toBe("OPENCODE_CONFIG='/home/user/it'\"'\"'s a label/config.json' opencode --standalone");
  });
  it('escapes shell substitution inside POSIX single quotes', () => {
    expect(opencodeLaunchCommand('/tmp/$(echo bad)`bad`/config.json'))
      .toBe("OPENCODE_CONFIG='/tmp/$(echo bad)`bad`/config.json' opencode --standalone");
  });
  it('quotes a Windows path for PowerShell', () => {
    expect(opencodeLaunchCommand("C:\\Users\\O'Brien\\config.json"))
      .toBe("$env:OPENCODE_CONFIG = 'C:\\Users\\O''Brien\\config.json'; opencode --standalone");
  });
  it('supports Windows network paths', () => {
    expect(opencodeLaunchCommand('\\\\server\\labels\\config.json'))
      .toBe("$env:OPENCODE_CONFIG = '\\\\server\\labels\\config.json'; opencode --standalone");
  });
});
