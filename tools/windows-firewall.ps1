# SPDX-License-Identifier: MIT OR Apache-2.0
<#
.SYNOPSIS
Manage Deckbench rules on the computer connected to the DJ network.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Install', 'Show', 'Remove')]
    [string]$Action = 'Show',
    [string]$InterfaceAlias,
    [string]$Python,
    [switch]$IncludeMetadata
)

$ErrorActionPreference = 'Stop'
$ruleNames = @('Deckbench-ProDJLink-UDP', 'Deckbench-ProDJLink-Metadata')

if ($Action -eq 'Show') {
    foreach ($name in $ruleNames) {
        $rule = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
        if ($rule) {
            $rule | Format-Table Name, Enabled, Direction, Action, Profile
            $rule | Get-NetFirewallApplicationFilter | Format-Table Program
            $rule | Get-NetFirewallInterfaceFilter | Format-Table InterfaceAlias
            $rule | Get-NetFirewallAddressFilter | Format-Table RemoteAddress
            $rule | Get-NetFirewallPortFilter | Format-Table Protocol, LocalPort
        }
    }
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this command in PowerShell opened as administrator on the DJ-connected PC'
}

if ($Action -eq 'Remove') {
    foreach ($name in $ruleNames) {
        if ((Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) -and
            $PSCmdlet.ShouldProcess($name, 'Remove firewall rule')) {
            Remove-NetFirewallRule -Name $name
        }
    }
    return
}

if (-not $InterfaceAlias) {
    throw 'Specify -InterfaceAlias with the DJ adapter name'
}
if (-not $Python) {
    $Python = & python -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw 'Could not locate Python, specify -Python explicitly' }
}
$Python = (Resolve-Path -LiteralPath $Python).Path
$addresses = @(Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -ne '127.0.0.1' })
if ($addresses.Count -eq 0) { throw 'The DJ adapter has no preferred IPv4 address' }
$subnets = @($addresses | ForEach-Object {
    $bytes = [Net.IPAddress]::Parse($_.IPAddress).GetAddressBytes()
    $remaining = [int]$_.PrefixLength
    for ($i = 0; $i -lt 4; $i++) {
        $bits = [Math]::Min(8, [Math]::Max(0, $remaining))
        $mask = [int](256 - [Math]::Pow(2, 8 - $bits))
        $bytes[$i] = $bytes[$i] -band $mask
        $remaining -= 8
    }
    '{0}/{1}' -f ([Net.IPAddress]::new($bytes)).ToString(), $_.PrefixLength
} | Sort-Object -Unique)
if ($subnets.Count -ne 1 -or $subnets[0] -eq '0.0.0.0/0') {
    throw 'Use a DJ adapter with one IPv4 subnet'
}
$names = @($ruleNames[0])
if ($IncludeMetadata) { $names += $ruleNames[1] }
foreach ($name in $names) {
    if (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) {
        throw "Rule $name already exists. Use -Action Show, or Remove before reinstalling"
    }
}
foreach ($name in $names) {
    $protocol = 'UDP'
    $ports = @('50000-50002')
    if ($name -eq $ruleNames[1]) {
        $protocol = 'TCP'
        $ports = @('1051', '12523')
    }
    if ($PSCmdlet.ShouldProcess("$Python on $InterfaceAlias from $($subnets[0])", "Allow $protocol $ports")) {
        New-NetFirewallRule -Name $name -DisplayName $name -Group 'Deckbench' `
            -Direction Inbound -Action Allow -Profile Any -InterfaceAlias $InterfaceAlias `
            -Program $Python -Protocol $protocol -LocalPort $ports -RemoteAddress $subnets[0]
    }
}
