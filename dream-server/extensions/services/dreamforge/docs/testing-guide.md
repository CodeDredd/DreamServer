# Testing Guide

How to run existing tests and write new ones for DreamForge.

---

## Running Tests

### Backend (Python)

```bash
cd extensions/services/dreamforge

# Run all tests
python -m pytest tests/ -v --tb=short

# Run a specific test file
python -m pytest tests/test_deep_security.py -v

# Run a specific test class
python -m pytest tests/test_deep_security.py::TestReadOnlyRules -v

# Run a specific test method
python -m pytest tests/test_deep_security.py::TestReadOnlyRules::test_echo -v

# Run with more verbose output
python -m pytest tests/ -v --tb=long

# Run only tests matching a keyword
python -m pytest tests/ -v -k "security"
```

### Frontend (JavaScript)

```bash
cd extensions/services/dreamforge/frontend

# Run all tests (single run)
npm test

# Run in watch mode (re-runs on file changes)
npm run test:watch
```

Frontend tests use [Vitest](https://vitest.dev/) with jsdom environment and [@testing-library/react](https://testing-library.com/docs/react-testing-library/intro/).

---

## Test Organization

### Backend Tests

All backend tests are in `extensions/services/dreamforge/tests/`. There are 40+ test files organized by area:

| Category | Key Files | What They Test |
|----------|-----------|----------------|
| Security | `test_deep_security.py`, `test_adversarial_security.py`, `test_shell_security.py`, `test_shell_parser.py` | Shell injection defense, command classification, read-only rules |
| Permissions | `test_permission_engine.py`, `test_permission_sanitizer.py`, `test_deep_permissions.py` | Mode behavior, session grants, rule evaluation, dangerous rule sanitization |
| Tools | `test_tool_pipeline.py`, `test_phase1_tools.py`, `test_final_tools.py`, `test_tool_depth.py` | Tool execution, pipeline steps, individual tool behavior |
| Agent | `test_deep_agent.py`, `test_e2e.py` | Query loop, WebSocket message flow, rate limiting |
| MCP | `test_deep_mcp.py` | Transport config, resource loading, sampling |
| Models | `test_models_router.py` | Pydantic model validation |
| Paths | `test_path_validator.py` | Workspace containment, sensitive files, symlinks |
| Features | `test_new_features.py`, `test_bug_fixes.py` | Specific features and regression tests |

### Frontend Tests

Frontend tests are in `extensions/services/dreamforge/frontend/src/components/__tests__/`:

| File | What It Tests |
|------|---------------|
| `MessageBubble.test.jsx` | Message rendering, markdown, code blocks |
| `ModeSwitch.test.jsx` | Permission mode selector |
| `StatusBar.test.jsx` | Connection status, model display |

---

## Writing a New Backend Test

### Basic Pattern

Tests are self-contained — they add the project root to `sys.path` and import directly:

```python
"""Tests for my_module."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.builtin.my_tool import MyTool
from models.tools import ToolResult


class TestMyTool:
    """Test suite for MyTool."""

    def test_basic_functionality(self):
        """Test the happy path."""
        tool = MyTool()
        assert tool.name == "my_tool"
        assert tool.access_level.value == "read"

    def test_parameter_validation(self):
        """Test that required parameters are defined."""
        tool = MyTool()
        params = tool.get_parameters()
        assert len(params) > 0
        assert params[0].required is True
```

### Parametrized Tests

Use `pytest.mark.parametrize` for testing multiple inputs:

```python
import pytest

@pytest.mark.parametrize("cmd,expected", [
    ("echo hello", FlagVerdict.READ),
    ("ls -la", FlagVerdict.READ),
    ("rm file.txt", FlagVerdict.EXECUTE),
    ("sed -i 's/a/b/' file.txt", FlagVerdict.WRITE),
])
def test_command_classification(cmd, expected):
    result = evaluate_command(cmd)
    assert result == expected
```

### Async Tests

For testing async functions:

```python
import asyncio
import pytest

@pytest.mark.asyncio
async def test_async_tool_execution():
    tool = MyTool()
    ctx = ToolContext(
        working_directory="/workspace",
        session_id="test-session",
        abort_event=asyncio.Event(),
    )
    result = await tool.execute({"input": "test"}, ctx)
    assert not result.is_error
```

### Using Mocks

```python
from unittest.mock import AsyncMock, MagicMock, patch

class TestWithMocks:
    def test_external_dependency(self):
        with patch("llm.client.LLMClient") as mock_client:
            mock_client.return_value.chat.return_value = AsyncMock(
                return_value={"choices": [{"message": {"content": "test"}}]}
            )
            # ... test code that uses the LLM client
```

### Testing Security Rules

```python
from security_engine.shell_parser import parse_command, SecurityVerdict

class TestSecurityRules:
    def test_safe_command(self):
        result = parse_command("echo hello")
        assert result.verdict == SecurityVerdict.SAFE

    def test_dangerous_injection(self):
        result = parse_command("echo $(cat /etc/passwd)")
        assert result.verdict == SecurityVerdict.DANGEROUS

    def test_ask_command(self):
        result = parse_command("curl https://example.com")
        assert result.verdict == SecurityVerdict.ASK
```

---

## Writing a New Frontend Test

### Basic Component Test

```jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MyComponent from '../MyComponent'

describe('MyComponent', () => {
  it('renders correctly', () => {
    render(<MyComponent title="Test" />)
    expect(screen.getByText('Test')).toBeDefined()
  })

  it('handles click events', async () => {
    const onClick = vi.fn()
    render(<MyComponent onClick={onClick} />)
    await screen.getByRole('button').click()
    expect(onClick).toHaveBeenCalledOnce()
  })
})
```

### Testing with ForgeContext

Components that use `useForge()` need to be wrapped in the context provider:

```jsx
import { ForgeProvider } from '../../contexts/ForgeContext'

function renderWithContext(component) {
  return render(
    <ForgeProvider>
      {component}
    </ForgeProvider>
  )
}

it('shows connection status', () => {
  renderWithContext(<StatusBar />)
  // ... assertions
})
```

### Test Configuration

Frontend tests are configured in `vite.config.js`:

```javascript
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './src/test-setup.js',
}
```

The `test-setup.js` file configures the test environment (e.g., DOM mocks).

---

## Test Conventions

- **File naming:** `test_{module_name}.py` for backend, `{Component}.test.jsx` for frontend
- **Class naming:** `TestFeatureName` (PascalCase, prefixed with Test)
- **Method naming:** `test_what_it_tests` (snake_case, prefixed with test_)
- **One assertion per concept** — each test should verify one behavior
- **No external dependencies** — tests should not require a running LLM server, database, or network access
- **Self-contained imports** — each test file includes its own `sys.path.insert` for the project root

---

## What to Test When Contributing

- **New tool:** Test parameter schema, execute with valid/invalid inputs, error handling
- **Security change:** Test both blocked and allowed patterns, edge cases
- **Permission change:** Test all 4 modes, grant/deny behavior
- **Frontend component:** Test rendering, user interaction, context integration
- **Bug fix:** Add a regression test that would have caught the original bug
