// Package wallets holds the catalog of known browser-extension
// wallet directories and the LevelDB-vault extractor.
//
// Separated from the regex-DSL engine because binary wallet
// extraction requires a real key-value store reader (goleveldb),
// not a text matcher. The output of this package feeds synthetic
// JSON files into the normal DSL pipeline downstream.
package wallets

// KnownExtension names one Chromium / Chromium-fork wallet
// extension by its universal id + a stable family slug.
type KnownExtension struct {
	ID     string // Chromium extension id, e.g. 'nkbihfbeogaeaoehlefnkodbefgpgknn'
	Family string // slug matching eyenet/stealer/families/<slug>.yaml, e.g. 'metamask'
	Name   string // human display name
}

// KnownExtensions is the authoritative list of wallet extension ids
// the extractor targets. Adding a wallet here is sufficient to pick
// it up on the next --mode extract-wallets run.
var KnownExtensions = []KnownExtension{
	{"nkbihfbeogaeaoehlefnkodbefgpgknn", "metamask", "MetaMask"},
	{"fnjhmkhhmkbjkkabndcnnogagogbneec", "ronin_wallet", "Ronin Wallet"},
	{"bfnaelmomeimhlpmgjnjophhpkkoljpa", "phantom", "Phantom"},
	{"egjidjbpglichdcondbcbdnbeeppgdph", "trust_wallet", "Trust Wallet"},
	{"fhbohimaelbohpjbbldcngcnapndodjp", "binance_chain", "Binance Chain Wallet"},
	{"ibnejdfjmmkpcnlpebklmnkoeoihofec", "tronlink", "TronLink"},
	{"ffnbelfdoeiohenkjibnmadjiehjhajb", "yoroi", "Yoroi"},
	{"acmacodkjbdgmoleebolmdjonilkdbch", "rabby", "Rabby"},
	{"ejbalbakoplchlghecdalmeeeajnimhm", "metamask_legacy", "MetaMask (legacy id)"},
	{"hnfanknocfeofbddgcijnmhnfnkdnaad", "coinbase_wallet", "Coinbase Wallet"},
	{"jblndlipeogpafnldhgmapagcccfchpi", "kaikas", "Kaikas"},
	{"amkmjjmmflddogmhpjloimipbofnfjih", "wombat", "Wombat"},
	{"ojggmmagiewdcdolkilbogcjpbpjakfj", "argent_x", "Argent X"},
	{"nphplpgoakhhjchkkhmiggakijnkhfnd", "ton_wallet", "TON Wallet"},
}

// LookupByID returns the KnownExtension for an id and whether it was
// found. The id is case-sensitive; Chromium normalizes all extension
// ids to lowercase 32-character strings on install.
func LookupByID(id string) (KnownExtension, bool) {
	for _, e := range KnownExtensions {
		if e.ID == id {
			return e, true
		}
	}
	return KnownExtension{}, false
}
