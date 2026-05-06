param(
    [string]$Project = "projects\example-subreddit-faq",
    [switch]$SkipExtract
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $scriptDir)

if ($SkipExtract) {
    reddit-researcher run $Project --skip-extract
} else {
    reddit-researcher run $Project
}
