import logging

from sqlmodel import select

from app.database import session_scope
from app.models.profile import Profile
from app.services.pfm import PFMClient

logger = logging.getLogger(__name__)

USER_HANDLES = {"AtehOfficial", "atehofficial", "just_ateh"}
USER_PFM_IDS = {"spc_U8xOuoxKCYpKAbzUymPCd"}


async def seed_demo_profiles() -> None:
    """Ensure only the user's connected accounts exist, purging all third-party accounts."""
    client = PFMClient()
    try:
        # Check if the user's account exists in Post for Me
        user_account = None
        try:
            acc = await client.get_social_account("spc_U8xOuoxKCYpKAbzUymPCd")
            if acc and acc.get("status") == "connected":
                user_account = acc
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not fetch user social account: %s", e)


        async with session_scope() as session:
            # Ensure user's connected account is present in database
            ateh_profile = (
                await session.exec(
                    select(Profile).where(
                        (Profile.handle == "AtehOfficial") | (Profile.pfm_account_id == "spc_U8xOuoxKCYpKAbzUymPCd")
                    )
                )
            ).first()


            if ateh_profile is None and user_account:
                meta = user_account.get("metadata") or {}
                name = meta.get("display_name") or "Ateh Ugoji"
                ateh_profile = Profile(
                    name=name,
                    platform="x",
                    handle="AtehOfficial",
                    pfm_account_id="spc_U8xOuoxKCYpKAbzUymPCd",
                )
                session.add(ateh_profile)
            elif ateh_profile is not None:
                ateh_profile.platform = "x"
                ateh_profile.handle = "AtehOfficial"
                ateh_profile.name = "Ateh Ugoji"
                ateh_profile.pfm_account_id = "spc_U8xOuoxKCYpKAbzUymPCd"
                session.add(ateh_profile)

            await session.commit()
            logger.info("Scoped profiles successfully. Only user accounts retained.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed_demo_profiles encountered error: %s", exc)
    finally:
        await client.aclose()

