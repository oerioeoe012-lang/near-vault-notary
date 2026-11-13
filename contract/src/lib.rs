//! Note registry: maps a stable note id to the chain of IPFS CIDs it was
//! published under. No note text is stored on chain.
//!
//! Rules
//! * The first account to register a note id becomes its author.
//! * Only that author may append versions.
//! * A new version must name the current CID as its predecessor, so the
//!   chain cannot fork and no version is silently skipped.

use near_sdk::json_types::U64;
use near_sdk::store::LookupMap;
use near_sdk::{env, log, near, require, AccountId};

const MAX_ID_LEN: usize = 64;
const MAX_CID_LEN: usize = 100;

#[near(serializers = [json, borsh])]
#[derive(Clone)]
pub struct Version {
    pub cid: String,
    pub prev_cid: Option<String>,
    /// Block timestamp, nanoseconds since Unix epoch (string in JSON).
    pub timestamp_ns: U64,
    pub block_height: U64,
    pub author: AccountId,
}

#[near(serializers = [json, borsh])]
#[derive(Clone)]
pub struct NoteRecord {
    pub author: AccountId,
    pub versions: Vec<Version>,
}

#[near(contract_state)]
pub struct Contract {
    notes: LookupMap<String, NoteRecord>,
}

impl Default for Contract {
    fn default() -> Self {
        Self { notes: LookupMap::new(b"n") }
    }
}

#[near]
impl Contract {
    /// Register a new note (prev_cid = null) or append a new version.
    pub fn publish(&mut self, note_id: String, cid: String, prev_cid: Option<String>) -> U64 {
        require!(!note_id.is_empty() && note_id.len() <= MAX_ID_LEN, "invalid note_id");
        require!(!cid.is_empty() && cid.len() <= MAX_CID_LEN, "invalid cid");
        let caller = env::predecessor_account_id();
        let version = Version {
            cid: cid.clone(),
            prev_cid: prev_cid.clone(),
            timestamp_ns: U64(env::block_timestamp()),
            block_height: U64(env::block_height()),
            author: caller.clone(),
        };

        let number = match self.notes.get_mut(&note_id) {
            None => {
                require!(prev_cid.is_none(), "unknown note: first version must have prev_cid = null");
                self.notes.insert(note_id.clone(), NoteRecord { author: caller.clone(), versions: vec![version] });
                1
            }
            Some(record) => {
                require!(record.author == caller, "only the original author may publish new versions");
                let current = &record.versions.last().expect("record has versions").cid;
                require!(prev_cid.as_ref() == Some(current), "prev_cid must equal the current cid");
                require!(&cid != current, "cid unchanged");
                record.versions.push(version);
                record.versions.len()
            }
        };

        // NEP-297 style event so indexers can follow publications.
        log!(
            "EVENT_JSON:{{\"standard\":\"note_registry\",\"version\":\"1.0.0\",\"event\":\"publish\",\"data\":[{{\"note_id\":\"{}\",\"cid\":\"{}\",\"version\":{},\"author\":\"{}\"}}]}}",
            note_id, cid, number, caller
        );
        U64(number as u64)
    }

    /// Full record: author plus every version, oldest first.
    pub fn get_note(&self, note_id: String) -> Option<NoteRecord> {
        self.notes.get(&note_id).cloned()
    }

    /// Only the current version.
    pub fn get_latest(&self, note_id: String) -> Option<Version> {
        self.notes.get(&note_id).and_then(|r| r.versions.last().cloned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn as_account(name: &str) {
        let ctx = VMContextBuilder::new()
            .predecessor_account_id(name.parse().unwrap())
            .block_timestamp(1_700_000_000_000_000_000)
            .build();
        testing_env!(ctx);
    }

    #[test]
    fn register_and_append() {
        let mut c = Contract::default();
        as_account("alice.testnet");
        assert_eq!(c.publish("n1".into(), "cid1".into(), None).0, 1);
        assert_eq!(c.publish("n1".into(), "cid2".into(), Some("cid1".into())).0, 2);
        let rec = c.get_note("n1".into()).unwrap();
        assert_eq!(rec.author.as_str(), "alice.testnet");
        assert_eq!(rec.versions[1].prev_cid.as_deref(), Some("cid1"));
        assert_eq!(c.get_latest("n1".into()).unwrap().cid, "cid2");
        assert!(c.get_note("missing".into()).is_none());
    }

    #[test]
    #[should_panic(expected = "only the original author")]
    fn other_account_cannot_append() {
        let mut c = Contract::default();
        as_account("alice.testnet");
        c.publish("n1".into(), "cid1".into(), None);
        as_account("mallory.testnet");
        c.publish("n1".into(), "evil".into(), Some("cid1".into()));
    }

    #[test]
    #[should_panic(expected = "prev_cid must equal the current cid")]
    fn stale_predecessor_rejected() {
        let mut c = Contract::default();
        as_account("alice.testnet");
        c.publish("n1".into(), "cid1".into(), None);
        c.publish("n1".into(), "cid2".into(), Some("cid1".into()));
        c.publish("n1".into(), "cid3".into(), Some("cid1".into()));
    }

    #[test]
    #[should_panic(expected = "first version must have prev_cid = null")]
    fn first_version_without_prev() {
        let mut c = Contract::default();
        as_account("alice.testnet");
        c.publish("n1".into(), "cid1".into(), Some("x".into()));
    }
}
