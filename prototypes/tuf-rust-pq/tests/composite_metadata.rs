use async_trait::async_trait;
use aws_lc_rs::rand::{SecureRandom, SystemRandom};
use aws_lc_rs::signature::{EcdsaKeyPair, ECDSA_P256_SHA256_ASN1_SIGNING};
use sequoia_openpgp as openpgp;
use std::collections::HashMap;
use std::error::Error;
use std::fmt;
use std::num::NonZeroU64;
use std::sync::{Arc, Mutex};

use openpgp::cert::{CertBuilder, CipherSuite};
use openpgp::packet::signature::SignatureBuilder;
use openpgp::parse::Parse;
use openpgp::policy::StandardPolicy;
use openpgp::serialize::SerializeInto;
use openpgp::types::{HashAlgorithm, KeyFlags, SignatureType};
use openpgp::{Cert, Packet, PacketPile, Profile};
use tough::editor::signed::SignedRole;
use tough::key_source::KeySource;
use tough::schema::key::{Ed25519Key, Ed25519Scheme, Key, OpenPgpKey, OpenPgpScheme};
use tough::schema::{
    DelegatedRole, DelegatedTargets, Delegations, KeyHolder, PathPattern, PathSet, Role, RoleKeys,
    RoleType, Root, Signature, Signed, Targets,
};
use tough::sign::Sign;

const ED25519_SIGNATURE_BYTES: usize = 64;
const ML_DSA_65_SIGNATURE_BYTES: usize = 3309;

#[derive(Clone)]
struct CompositeSigner {
    cert: Cert,
    public_projection: Vec<u8>,
    signed_messages: Arc<Mutex<Vec<Vec<u8>>>>,
}

impl fmt::Debug for CompositeSigner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CompositeSigner")
            .field("fingerprint", &self.cert.fingerprint())
            .finish_non_exhaustive()
    }
}

impl CompositeSigner {
    fn generate() -> openpgp::Result<Self> {
        let (cert, _) = CertBuilder::new()
            .set_profile(Profile::RFC9580)?
            .set_cipher_suite(CipherSuite::MLDSA65_Ed25519)
            .set_primary_key_flags(KeyFlags::empty().set_certification())
            .add_userid("Disposable TUF RFC 9980 fixture <fixture.invalid>")
            .add_signing_subkey()
            .generate()?;
        let public_projection = cert.clone().strip_secret_key_material().to_vec()?;

        Ok(Self {
            cert,
            public_projection,
            signed_messages: Arc::new(Mutex::new(Vec::new())),
        })
    }
}

fn openpgp_key(public_projection: Vec<u8>) -> Key {
    Key::OpenPgp {
        keyval: OpenPgpKey {
            public: public_projection.into(),
            _extra: HashMap::new(),
        },
        scheme: OpenPgpScheme::OpenPgpRfc9980MlDsa65Ed25519Sha512,
        _extra: HashMap::new(),
    }
}

fn alternate_public_projection(cert: &Cert) -> openpgp::Result<Vec<u8>> {
    cert.clone()
        .insert_packets(openpgp::packet::UserID::from(
            "Alternate disposable projection <alias.invalid>",
        ))?
        .0
        .strip_secret_key_material()
        .to_vec()
}

#[async_trait]
impl Sign for CompositeSigner {
    fn tuf_key(&self) -> Key {
        openpgp_key(self.public_projection.clone())
    }

    async fn sign(
        &self,
        msg: &[u8],
        _rng: &(dyn SecureRandom + Sync),
    ) -> Result<Vec<u8>, Box<dyn Error + Send + Sync + 'static>> {
        self.signed_messages.lock().unwrap().push(msg.to_vec());

        let policy = StandardPolicy::new();
        let mut keypair = self
            .cert
            .keys()
            .secret()
            .with_policy(&policy, None)
            .supported()
            .alive()
            .revoked(false)
            .for_signing()
            .next()
            .ok_or_else(|| "fixture has no signing key".to_string())?
            .key()
            .clone()
            .into_keypair()?;
        let issuer = keypair.public().fingerprint();
        let signature = SignatureBuilder::new(SignatureType::Binary)
            .set_hash_algo(HashAlgorithm::SHA512)
            .set_issuer_fingerprint(issuer)?
            .sign_message(&mut keypair, msg)?;

        Ok(Packet::from(signature).to_vec()?)
    }
}

#[async_trait]
impl KeySource for CompositeSigner {
    async fn as_sign(&self) -> Result<Box<dyn Sign>, Box<dyn Error + Send + Sync + 'static>> {
        Ok(Box::new(self.clone()))
    }

    async fn write(
        &self,
        _value: &str,
        _key_id_hex: &str,
    ) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
        Err("the disposable in-memory key source is read-only".into())
    }
}

fn role_keys(key_id: tough::schema::decoded::Decoded<tough::schema::decoded::Hex>) -> RoleKeys {
    RoleKeys {
        keyids: vec![key_id],
        threshold: NonZeroU64::new(1).unwrap(),
        _extra: HashMap::new(),
    }
}

fn corrupt_component(signature: &[u8], from_end: usize) -> Vec<u8> {
    let mut corrupted = signature.to_vec();
    let index = corrupted
        .len()
        .checked_sub(from_end)
        .expect("signature packet contains the selected RFC 9980 component");
    corrupted[index] ^= 0x01;
    corrupted
}

fn with_undefined_openpgp_extension(mut key: Key) -> Key {
    let Key::OpenPgp { _extra, .. } = &mut key else {
        unreachable!("the composite fixture always returns an OpenPGP key");
    };
    _extra.insert("rr1-alias".to_owned(), serde_json::json!(true));
    key
}

fn with_undefined_openpgp_keyval_extension(mut key: Key) -> Key {
    let Key::OpenPgp { keyval, .. } = &mut key else {
        unreachable!("the composite fixture always returns an OpenPGP key");
    };
    keyval
        ._extra
        .insert("rr1-keyval-alias".to_owned(), serde_json::json!(true));
    key
}

fn generate_ecdsa_signer() -> Result<EcdsaKeyPair, Box<dyn Error + Send + Sync + 'static>> {
    let rng = SystemRandom::new();
    let document = EcdsaKeyPair::generate_pkcs8(&ECDSA_P256_SHA256_ASN1_SIGNING, &rng)?;
    Ok(EcdsaKeyPair::from_pkcs8(
        &ECDSA_P256_SHA256_ASN1_SIGNING,
        document.as_ref(),
    )?)
}

fn with_ecdsa_compatibility_extension(mut key: Key) -> Key {
    let Key::Ecdsa { _extra, .. } = &mut key else {
        unreachable!("the conventional fixture always returns an ECDSA key");
    };
    _extra.insert("existing-key-extension".to_owned(), serde_json::json!(true));
    key
}

#[tokio::test(flavor = "current_thread")]
async fn root_rejects_undefined_openpgp_extensions(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let signer = CompositeSigner::generate()?;
    let key = signer.tuf_key();
    let invalid_keys = [
        with_undefined_openpgp_extension(key.clone()),
        with_undefined_openpgp_keyval_extension(key),
    ];

    for invalid_key in invalid_keys {
        let invalid_key_id = invalid_key.key_id()?;
        let root_keys = role_keys(invalid_key_id.clone());
        let mut roles = HashMap::new();
        roles.insert(RoleType::Root, root_keys.clone());
        roles.insert(RoleType::Targets, root_keys.clone());
        roles.insert(RoleType::Snapshot, root_keys.clone());
        roles.insert(RoleType::Timestamp, root_keys);
        let root = Root {
            spec_version: "1.0.36".to_owned(),
            consistent_snapshot: true,
            version: NonZeroU64::new(1).unwrap(),
            expires: "2999-01-01T00:00:00Z".parse().unwrap(),
            keys: HashMap::from([(invalid_key_id.clone(), invalid_key)]),
            roles,
            _extra: HashMap::new(),
        };
        let signature = signer
            .sign(&root.canonical_form()?, &SystemRandom::new())
            .await?;
        let signed = Signed {
            signed: root,
            signatures: vec![tough::schema::Signature {
                keyid: invalid_key_id,
                sig: signature.into(),
            }],
        };
        signed
            .signed
            .verify_role(&signed)
            .expect_err("undefined OpenPGP key fields must not verify");
        let encoded = serde_json::to_vec(&signed)?;
        assert!(
            serde_json::from_slice::<Signed<Root>>(&encoded).is_err(),
            "undefined OpenPGP key fields must be rejected during metadata ingestion"
        );
    }

    Ok(())
}

#[test]
fn conventional_keys_retain_existing_extra_field_compatibility(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let key = Key::Ed25519 {
        keyval: Ed25519Key {
            public: vec![0; 32].into(),
            _extra: HashMap::from([(
                "existing-keyval-extension".to_owned(),
                serde_json::json!(true),
            )]),
        },
        scheme: Ed25519Scheme::Ed25519,
        _extra: HashMap::from([("existing-key-extension".to_owned(), serde_json::json!(true))]),
    };
    let key_id = key.key_id()?;
    let root_keys = role_keys(key_id.clone());
    let mut roles = HashMap::new();
    roles.insert(RoleType::Root, root_keys.clone());
    roles.insert(RoleType::Targets, root_keys.clone());
    roles.insert(RoleType::Snapshot, root_keys.clone());
    roles.insert(RoleType::Timestamp, root_keys);
    let root = Root {
        spec_version: "1.0.36".to_owned(),
        consistent_snapshot: true,
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        keys: HashMap::from([(key_id, key)]),
        roles,
        _extra: HashMap::new(),
    };

    let encoded = serde_json::to_vec(&root)?;
    let reparsed: Root = serde_json::from_slice(&encoded)?;
    assert_eq!(reparsed.keys.len(), 1);

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn root_retains_conventional_ecdsa_tuf_id_threshold_identity(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let signer = generate_ecdsa_signer()?;
    let key = signer.tuf_key();
    let alias = with_ecdsa_compatibility_extension(key.clone());
    let key_id = key.key_id()?;
    let alias_id = alias.key_id()?;
    assert_ne!(key_id, alias_id);

    let root_keys = RoleKeys {
        keyids: vec![key_id.clone(), alias_id.clone()],
        threshold: NonZeroU64::new(2).unwrap(),
        _extra: HashMap::new(),
    };
    let mut roles = HashMap::new();
    roles.insert(RoleType::Root, root_keys);
    roles.insert(RoleType::Targets, role_keys(key_id.clone()));
    roles.insert(RoleType::Snapshot, role_keys(key_id.clone()));
    roles.insert(RoleType::Timestamp, role_keys(key_id.clone()));
    let root = Root {
        spec_version: "1.0.36".to_owned(),
        consistent_snapshot: true,
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        keys: HashMap::from([(key_id.clone(), key), (alias_id.clone(), alias)]),
        roles,
        _extra: HashMap::new(),
    };
    let canonical = root.canonical_form()?;
    let rng = SystemRandom::new();
    let signatures = vec![
        Signature {
            keyid: key_id,
            sig: Sign::sign(&signer, &canonical, &rng).await?.into(),
        },
        Signature {
            keyid: alias_id,
            sig: Sign::sign(&signer, &canonical, &rng).await?.into(),
        },
    ];

    let one_signature = Signed {
        signed: root.clone(),
        signatures: vec![signatures[0].clone()],
    };
    root.verify_role(&one_signature)
        .expect_err("one conventional TUF key ID must not satisfy threshold 2");

    let encoded = serde_json::to_vec(&Signed {
        signed: root,
        signatures,
    })?;
    let reparsed: Signed<Root> = serde_json::from_slice(&encoded)?;
    reparsed.signed.verify_role(&reparsed)?;

    let mut duplicate_key_id = reparsed.clone();
    duplicate_key_id
        .signatures
        .push(duplicate_key_id.signatures[0].clone());
    duplicate_key_id
        .signed
        .verify_role(&duplicate_key_id)
        .expect_err("root verification must reject a repeated signature key ID");

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn delegations_retain_conventional_ecdsa_tuf_id_threshold_identity(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let signer = generate_ecdsa_signer()?;
    let key = signer.tuf_key();
    let alias = with_ecdsa_compatibility_extension(key.clone());
    let key_id = key.key_id()?;
    let alias_id = alias.key_id()?;
    assert_ne!(key_id, alias_id);

    let role_name = "delegated";
    let delegations = Delegations {
        keys: HashMap::from([(key_id.clone(), key), (alias_id.clone(), alias)]),
        roles: vec![DelegatedRole {
            name: role_name.to_owned(),
            keyids: vec![key_id.clone(), alias_id.clone()],
            threshold: NonZeroU64::new(2).unwrap(),
            paths: PathSet::Paths(vec![PathPattern::new("*")?]),
            terminating: false,
            targets: None,
        }],
    };
    let encoded = serde_json::to_vec(&delegations)?;
    let reparsed: Delegations = serde_json::from_slice(&encoded)?;
    let targets = Targets {
        spec_version: "1.0.36".to_owned(),
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        targets: HashMap::new(),
        delegations: None,
        _extra: HashMap::new(),
    };
    let canonical = targets.canonical_form()?;
    let rng = SystemRandom::new();
    let signatures = vec![
        Signature {
            keyid: key_id,
            sig: Sign::sign(&signer, &canonical, &rng).await?.into(),
        },
        Signature {
            keyid: alias_id,
            sig: Sign::sign(&signer, &canonical, &rng).await?.into(),
        },
    ];

    let one_signature = Signed {
        signed: targets.clone(),
        signatures: vec![signatures[0].clone()],
    };
    reparsed
        .verify_role(&one_signature, role_name)
        .expect_err("one conventional TUF key ID must not satisfy delegated threshold 2");

    let signed = Signed {
        signed: targets,
        signatures,
    };
    reparsed.verify_role(&signed, role_name)?;

    let mut duplicate_key_id = signed;
    duplicate_key_id
        .signatures
        .push(duplicate_key_id.signatures[0].clone());
    reparsed
        .verify_role(&duplicate_key_id, role_name)
        .expect_err("delegation verification must reject a repeated signature key ID");

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn root_rejects_unused_undefined_openpgp_extensions(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let signer = CompositeSigner::generate()?;
    let clean_key = signer.tuf_key();
    let clean_key_id = clean_key.key_id()?;
    let unused_key = CompositeSigner::generate()?.tuf_key();
    let invalid_keys = [
        with_undefined_openpgp_extension(unused_key.clone()),
        with_undefined_openpgp_keyval_extension(unused_key),
    ];

    for invalid_key in invalid_keys {
        let invalid_key_id = invalid_key.key_id()?;
        assert_ne!(clean_key_id, invalid_key_id);
        let root_keys = role_keys(clean_key_id.clone());
        let mut roles = HashMap::new();
        roles.insert(RoleType::Root, root_keys.clone());
        roles.insert(RoleType::Targets, root_keys.clone());
        roles.insert(RoleType::Snapshot, root_keys.clone());
        roles.insert(RoleType::Timestamp, root_keys);
        let root = Root {
            spec_version: "1.0.36".to_owned(),
            consistent_snapshot: true,
            version: NonZeroU64::new(1).unwrap(),
            expires: "2999-01-01T00:00:00Z".parse().unwrap(),
            keys: HashMap::from([
                (clean_key_id.clone(), clean_key.clone()),
                (invalid_key_id, invalid_key),
            ]),
            roles,
            _extra: HashMap::new(),
        };
        let key_sources: Vec<Box<dyn KeySource>> = vec![Box::new(signer.clone())];
        let signed = SignedRole::new(
            root.clone(),
            &KeyHolder::Root(root),
            &key_sources,
            &SystemRandom::new(),
        )
        .await?;
        signed.signed().signed.verify_role(signed.signed())?;

        let encoded = serde_json::to_vec(signed.signed())?;
        assert!(
            serde_json::from_slice::<Signed<Root>>(&encoded).is_err(),
            "root metadata must reject an unused provisional OpenPGP key with undefined fields"
        );
    }

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn delegations_reject_unused_undefined_openpgp_extensions(
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let signer = CompositeSigner::generate()?;
    let clean_key = signer.tuf_key();
    let clean_key_id = clean_key.key_id()?;
    let unused_key = CompositeSigner::generate()?.tuf_key();
    let invalid_keys = [
        with_undefined_openpgp_extension(unused_key.clone()),
        with_undefined_openpgp_keyval_extension(unused_key),
    ];

    for invalid_key in invalid_keys {
        let invalid_key_id = invalid_key.key_id()?;
        assert_ne!(clean_key_id, invalid_key_id);
        let role_name = "delegated";
        let delegations = Delegations {
            keys: HashMap::from([
                (clean_key_id.clone(), clean_key.clone()),
                (invalid_key_id, invalid_key),
            ]),
            roles: vec![DelegatedRole {
                name: role_name.to_owned(),
                keyids: vec![clean_key_id.clone()],
                threshold: NonZeroU64::new(1).unwrap(),
                paths: PathSet::Paths(vec![PathPattern::new("*")?]),
                terminating: false,
                targets: None,
            }],
        };
        let delegated_targets = Targets {
            spec_version: "1.0.36".to_owned(),
            version: NonZeroU64::new(1).unwrap(),
            expires: "2999-01-01T00:00:00Z".parse().unwrap(),
            targets: HashMap::new(),
            delegations: None,
            _extra: HashMap::new(),
        };
        let key_sources: Vec<Box<dyn KeySource>> = vec![Box::new(signer.clone())];
        let signed = SignedRole::new(
            DelegatedTargets {
                name: role_name.to_owned(),
                targets: delegated_targets,
            },
            &KeyHolder::Delegations(delegations.clone()),
            &key_sources,
            &SystemRandom::new(),
        )
        .await?;
        let signed_targets = signed.signed().clone().targets().1;
        delegations.verify_role(&signed_targets, role_name)?;

        let containing_targets = Targets {
            spec_version: "1.0.36".to_owned(),
            version: NonZeroU64::new(1).unwrap(),
            expires: "2999-01-01T00:00:00Z".parse().unwrap(),
            targets: HashMap::new(),
            delegations: Some(delegations),
            _extra: HashMap::new(),
        };
        let encoded = serde_json::to_vec(&containing_targets)?;
        assert!(
            serde_json::from_slice::<Targets>(&encoded).is_err(),
            "delegations metadata must reject an unused provisional OpenPGP key with undefined fields"
        );
    }

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn root_rejects_distinct_tuf_ids_for_one_composite_signing_key() -> openpgp::Result<()> {
    let signer = CompositeSigner::generate()?;
    let key = signer.tuf_key();
    let alias = openpgp_key(alternate_public_projection(&signer.cert)?);
    let key_id = key.key_id()?;
    let alias_id = alias.key_id()?;
    assert_ne!(key_id, alias_id);

    let root_keys = RoleKeys {
        keyids: vec![key_id.clone(), alias_id.clone()],
        threshold: NonZeroU64::new(2).unwrap(),
        _extra: HashMap::new(),
    };
    let mut roles = HashMap::new();
    roles.insert(RoleType::Root, root_keys);
    roles.insert(RoleType::Targets, role_keys(key_id.clone()));
    roles.insert(RoleType::Snapshot, role_keys(key_id.clone()));
    roles.insert(RoleType::Timestamp, role_keys(key_id.clone()));
    let root = Root {
        spec_version: "1.0.36".to_owned(),
        consistent_snapshot: true,
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        keys: HashMap::from([(key_id.clone(), key), (alias_id.clone(), alias)]),
        roles,
        _extra: HashMap::new(),
    };
    let key_sources: Vec<Box<dyn KeySource>> = vec![Box::new(signer)];
    let signed = SignedRole::new(
        root.clone(),
        &KeyHolder::Root(root),
        &key_sources,
        &SystemRandom::new(),
    )
    .await?;
    assert_eq!(signed.signed().signatures.len(), 1);

    let mut counterexample = signed.signed().clone();
    let mut relabeled = counterexample.signatures[0].clone();
    relabeled.keyid = alias_id;
    counterexample.signatures.push(relabeled);

    let encoded = serde_json::to_vec(&counterexample)?;
    let reparsed: Signed<Root> = serde_json::from_slice(&encoded)?;
    reparsed
        .signed
        .verify_role(&reparsed)
        .expect_err("one composite signing key must not satisfy threshold 2");

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn delegations_reject_distinct_tuf_ids_for_one_composite_signing_key() -> openpgp::Result<()>
{
    let signer = CompositeSigner::generate()?;
    let key = signer.tuf_key();
    let alias = openpgp_key(alternate_public_projection(&signer.cert)?);
    let key_id = key.key_id()?;
    let alias_id = alias.key_id()?;
    assert_ne!(key_id, alias_id);

    let role_name = "delegated";
    let mut delegations = Delegations {
        keys: HashMap::from([(key_id.clone(), key), (alias_id.clone(), alias)]),
        roles: vec![DelegatedRole {
            name: role_name.to_owned(),
            keyids: vec![key_id, alias_id.clone()],
            threshold: NonZeroU64::new(1).unwrap(),
            paths: PathSet::Paths(vec![PathPattern::new("*")?]),
            terminating: false,
            targets: None,
        }],
    };
    let targets = Targets {
        spec_version: "1.0.36".to_owned(),
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        targets: HashMap::new(),
        delegations: None,
        _extra: HashMap::new(),
    };
    let key_sources: Vec<Box<dyn KeySource>> = vec![Box::new(signer)];
    let signed = SignedRole::new(
        DelegatedTargets {
            name: role_name.to_owned(),
            targets,
        },
        &KeyHolder::Delegations(delegations.clone()),
        &key_sources,
        &SystemRandom::new(),
    )
    .await?;
    assert_eq!(signed.signed().signatures.len(), 1);

    delegations.roles[0].threshold = NonZeroU64::new(2).unwrap();
    let encoded_delegations = serde_json::to_vec(&delegations)?;
    let reparsed: Delegations = serde_json::from_slice(&encoded_delegations)?;
    let mut counterexample = signed.signed().clone().targets().1;
    let mut relabeled = counterexample.signatures[0].clone();
    relabeled.keyid = alias_id;
    counterexample.signatures.push(relabeled);
    reparsed
        .verify_role(&counterexample, role_name)
        .expect_err("one composite signing key must not satisfy delegated threshold 2");

    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn publisher_and_verifier_require_both_rfc9980_components() -> openpgp::Result<()> {
    let signer = CompositeSigner::generate()?;
    let key = signer.tuf_key();
    let key_id = key.key_id()?;
    let role_key = role_keys(key_id.clone());
    let mut roles = HashMap::new();
    roles.insert(RoleType::Root, role_key.clone());
    roles.insert(RoleType::Targets, role_key.clone());
    roles.insert(RoleType::Snapshot, role_key.clone());
    roles.insert(RoleType::Timestamp, role_key);
    let root = Root {
        spec_version: "1.0.36".to_owned(),
        consistent_snapshot: true,
        version: NonZeroU64::new(1).unwrap(),
        expires: "2999-01-01T00:00:00Z".parse().unwrap(),
        keys: HashMap::from([(key_id.clone(), key)]),
        roles,
        _extra: HashMap::new(),
    };
    let canonical_signed_bytes = root.canonical_form()?;
    let key_sources: Vec<Box<dyn KeySource>> = vec![Box::new(signer.clone())];

    let signed = SignedRole::new(
        root.clone(),
        &KeyHolder::Root(root.clone()),
        &key_sources,
        &SystemRandom::new(),
    )
    .await?;

    assert_eq!(
        signer.signed_messages.lock().unwrap().as_slice(),
        &[canonical_signed_bytes]
    );
    root.verify_role(signed.signed())?;

    let mut duplicate_signature = signed.signed().clone();
    duplicate_signature
        .signatures
        .push(duplicate_signature.signatures[0].clone());
    let mut threshold_two_root = root.clone();
    threshold_two_root
        .roles
        .get_mut(&RoleType::Root)
        .unwrap()
        .threshold = NonZeroU64::new(2).unwrap();
    assert!(threshold_two_root
        .verify_role(&duplicate_signature)
        .is_err());

    let compact_outer = serde_json::to_vec(signed.signed())?;
    let reparsed: Signed<Root> = serde_json::from_slice(&compact_outer)?;
    root.verify_role(&reparsed)?;

    let signature_packet = signed.signed().signatures[0].sig.to_vec();
    let packets: Vec<Packet> = PacketPile::from_bytes(&signature_packet)?
        .into_children()
        .collect();
    assert_eq!(packets.len(), 1, "the TUF signature is exactly one packet");
    let Packet::Signature(signature) = &packets[0] else {
        panic!("the only packet must be a detached signature");
    };
    assert_eq!(signature.version(), 6);
    assert_eq!(signature.typ(), SignatureType::Binary);
    assert_eq!(
        signature.pk_algo(),
        openpgp::types::PublicKeyAlgorithm::MLDSA65_Ed25519
    );
    assert_eq!(signature.hash_algo(), HashAlgorithm::SHA512);
    assert_eq!(signature.issuer_fingerprints().count(), 1);

    let mut bad_ed25519 = signed.signed().clone();
    bad_ed25519.signatures[0].sig = corrupt_component(
        &signature_packet,
        ED25519_SIGNATURE_BYTES + ML_DSA_65_SIGNATURE_BYTES,
    )
    .into();
    assert!(root.verify_role(&bad_ed25519).is_err());

    let mut bad_ml_dsa = signed.signed().clone();
    bad_ml_dsa.signatures[0].sig =
        corrupt_component(&signature_packet, ML_DSA_65_SIGNATURE_BYTES).into();
    assert!(root.verify_role(&bad_ml_dsa).is_err());

    println!(
        "{}",
        serde_json::json!({
            "canonicalSignedBytes": signer.signed_messages.lock().unwrap()[0].len(),
            "compositeSigningKeyThresholdContributions": 1,
            "conventionalKeyExtraFieldCompatibilityRetained": true,
            "delegatedDistinctTufIdsForOneCompositeSigningKeyRejected": true,
            "distinctTufIdsForOneCompositeSigningKeyRejected": true,
            "duplicateCompositeSignatureRejected": true,
            "ed25519ComponentCorruptionRejected": true,
            "hash": "SHA-512",
            "issuerFingerprint": signature.issuer_fingerprints().next().unwrap().to_string(),
            "keyId": serde_json::to_value(&key_id)?,
            "keyType": "openpgp-rfc9580",
            "mlDsa65ComponentCorruptionRejected": true,
            "outerReformatVerified": true,
            "publicKeyAlgorithm": 30,
            "publicProjectionBytes": signer.public_projection.len(),
            "scheme": "openpgp-rfc9980-ml-dsa-65+ed25519-sha512",
            "signaturePacketBytes": signature_packet.len(),
            "signaturePacketCount": 1,
            "signatureType": 0,
            "signatureVersion": 6,
            "syntheticIndependence": "one generated composite key; no operator, custody, or underlying-key independence claim",
            "thresholdIdentity": "verified-v6-openpgp-signing-key-fingerprint",
            "thresholdTwoSatisfiedByOneCompositeKey": false,
            "undefinedOpenPgpExtensionsRejected": true,
            "unusedUndefinedOpenPgpKeysRejectedBeforeMetadataAcceptance": true,
            "verified": true
        })
    );

    Ok(())
}
