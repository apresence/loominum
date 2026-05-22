# Certificate Installation Script Templates

These templates are used to generate platform-specific certificate installation scripts with the actual certificate embedded.

## Template Variables

The following placeholders are replaced at runtime:

- `{{CERTIFICATE}}` - Replaced with the contents of `data/unbillicord/cert.pem`
- `{{CLIENT_URL}}` - Replaced with the executor's client connection URL (from config)

## Files

- `install-cert.sh` - Linux/Unix bash script template
- `install-cert.ps1` - Windows PowerShell script template

## How It Works

1. User runs: `curl -k https://host:port/install-cert.sh | sudo bash`
2. Server reads template from this directory
3. Server reads certificate from `data/unbillicord/cert.pem`
4. Server replaces `{{CERTIFICATE}}` and `{{CLIENT_URL}}` placeholders
5. Server returns the customized script
6. Script executes and installs the embedded certificate

## Editing Templates

When editing these templates:
- Keep the `{{CERTIFICATE}}` and `{{CLIENT_URL}}` placeholders intact
- Test changes by regenerating the cert and fetching the script
- Ensure proper escaping for shell/PowerShell syntax
