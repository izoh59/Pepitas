# --- Importations ---
import discord
from discord.ext import commands
from discord.ui import Button, View
import pytesseract
from PIL import Image
import io
import os
import re
import json
from dotenv import load_dotenv
load_dotenv()

# --- Configuration des intents ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

# --- ID des salons ---
SALON_AUTORISE_ID = 1366484630852862154
ID_SALON_COMMANDES = 1366889154805370910
ID_SALON_CLASSEMENT = 1366884051172200529

# --- Initialisation du bot ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Variables globales ---
attente_type = None
pseudos_detectes_actuels = []
utilisateur_demandeur = None
liens_pseudos = {}
classement_points = {}
action_en_cours = None
pseudos_non_associes_globaux = []
pseudos_perdants_actuels = []
pseudos_detectes_perdants = []


# Chargement de la configuration des points personnalisée
def charger_points_config():
    try:
        with open("points_config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"attaque": {}, "défense": {}}


points_config = charger_points_config()


# --- Fonction de recadrage dynamique ---
def recadrage_dynamique(image_obj):
    largeur, hauteur = image_obj.size
    data = pytesseract.image_to_data(image_obj,
                                     lang='fra',
                                     output_type=pytesseract.Output.DICT)
    ocr_data = [{
        'text': data['text'][i],
        'left': data['left'][i],
        'top': data['top'][i],
        'width': data['width'][i],
        'height': data['height'][i]
    } for i in range(len(data['text'])) if data['text'][i].strip()]
    x0_dyn = int(largeur * 0.06)
    y0_dyn = int(hauteur * 0.18)
    for word_data in ocr_data:
        if word_data['text'].strip().lower() == "de":
            x0_dyn = word_data['left']
            break
    for word_data in ocr_data:
        if "nom" in word_data['text'].lower(
        ) and word_data['top'] < hauteur * 0.5:
            y0_dyn = word_data['top'] + word_data['height']
            break
    x1 = int(largeur * 0.23)
    y1 = int(hauteur * 0.95)
    return image_obj.crop((x0_dyn, y0_dyn, x1, y1))


def est_dans_salon_autorise(ctx):
    return ctx.channel.id == SALON_AUTORISE_ID


async def mettre_a_jour_classement_epingle(guild):
    salon = guild.get_channel(ID_SALON_CLASSEMENT)
    if not salon:
        return

    try:
        async for message in salon.history(limit=None):
            await message.delete()
    except Exception as e:
        print(f"❌ Erreur lors de la suppression des messages : {e}")

    embed = discord.Embed(title="🏆 Classement actuel",
                          color=discord.Color.gold())
    lignes = []

    if not classement_points:
        lignes.append("📭 Aucun point enregistré pour le moment.")
    else:
        classement_trie = sorted(classement_points.items(),
                                 key=lambda item: item[1],
                                 reverse=True)
        for position, (discord_id, points) in enumerate(classement_trie,
                                                        start=1):
            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                except:
                    member = None

            if position == 1:
                icone = "🥇"
            elif position == 2:
                icone = "🥈"
            elif position == 3:
                icone = "🥉"
            else:
                icone = f"#{position}"

            mention = member.mention if member else f"(ID : {discord_id})"
            lignes.append(f"{icone} {mention} - {points} pts")

    embed.description = "\n".join(lignes)
    msg = await salon.send(embed=embed)
    await msg.pin()


@bot.event
async def on_ready():
    charger_donnees()  # Charge correctement liens_pseudos + classement_points
    print(f"✅ Bot connecté en tant que {bot.user}")
    await mettre_a_jour_classement_epingle(bot.guilds[0])
    salon_commandes = bot.get_channel(ID_SALON_COMMANDES)
    if salon_commandes:
        try:
            async for message in salon_commandes.history(limit=100):
                if message.author == bot.user:
                    await message.delete()
            await salon_commandes.send(embed=discord.Embed(
                title="📜 Commandes disponibles",
                description=(
                    "**!link @membre pseudo** – Lier un pseudo à un membre\n"
                    "**!unlink @membre pseudo** – Retirer un pseudo lié\n"
                    "**!user @membre** – Voir les pseudos et points d’un membre\n"
                    "**!classement** – Afficher le classement actuel\n"
                    "**!perco** – Envoyer un screen d'une attaque ou d'une défense\n"
                    "**!bareme** – Afficher le barème de points utilisé\n"
                    "**!setpoints type gagnants perdants points** – Définir un barème personnalisé (admin)\n"
                    "**!reset** – Réinitialiser le classement (admin)"
                ),
                color=discord.Color.blue()
            ))
        except Exception as e:
            print(f"❌ Erreur en envoyant la liste des commandes : {e}")


# --- Fonction ajouter un pseudo à un membre ---
@bot.command()
async def link(ctx, membre: discord.Member, *, pseudo: str):
    discord_id = membre.id
    if discord_id not in liens_pseudos:
        liens_pseudos[discord_id] = []
    if pseudo not in liens_pseudos[discord_id]:
        liens_pseudos[discord_id].append(pseudo)
        await ctx.send(f"✅ Le pseudo {pseudo} a été lié à {membre.mention}.")
        global pseudos_non_associes_globaux, action_en_cours
        if pseudo in pseudos_non_associes_globaux and action_en_cours:
            points = 15 if action_en_cours == "attaque" else 10
            classement_points[discord_id] = classement_points.get(
                discord_id, 0) + points
            pseudos_non_associes_globaux.remove(pseudo)
            await ctx.send(
                f"🆗 {pseudo} a reçu {points} points suite à l'action précédente."
            )
            await mettre_a_jour_classement_epingle(ctx.guild)
    else:
        await ctx.send(
            f"⚠️ Le pseudo {pseudo} est déjà lié à {membre.mention}.")
    sauvegarder_donnees()  # <--- à ajouter ici


# --- Fonction retirer un pseudo à un membre ---
@bot.command()
async def unlink(ctx, membre: discord.Member, *, pseudo: str):
    discord_id = membre.id
    if discord_id in liens_pseudos and pseudo in liens_pseudos[discord_id]:
        liens_pseudos[discord_id].remove(pseudo)
        await ctx.send(
            f"❌ Le pseudo {pseudo} a été retiré de {membre.mention}.")
        if not liens_pseudos[discord_id]:
            del liens_pseudos[discord_id]
    else:
        await ctx.send(
            f"⚠️ Le pseudo {pseudo} n'était pas lié à {membre.mention}.")
    sauvegarder_donnees()  # <--- à ajouter ici


# --- Fonction réinitialiser le classement ---
@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    """Réinitialise tous les scores à 0 après confirmation."""
    confirmation_msg = await ctx.send(
        "⚠️ Cette action va réinitialiser **le classement** à 0. Réagissez avec ✅ pour confirmer, ❌ pour annuler."
    )
    await confirmation_msg.add_reaction("✅")
    await confirmation_msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in [
            "✅", "❌"
        ] and reaction.message.id == confirmation_msg.id

    try:
        reaction, _ = await bot.wait_for("reaction_add",
                                         timeout=30.0,
                                         check=check)
    except asyncio.TimeoutError:
        await ctx.send("⏱️ Temps écoulé. Réinitialisation annulée.")
        return

    if str(reaction.emoji) == "✅":
        for user_id in classement_points:
            classement_points[user_id] = 0
        sauvegarder_donnees()
        await ctx.send("✅ Le classement a été réinitialisé à 0.")
        await mettre_a_jour_classement_epingle(
            ctx.guild)  # <- ici on passe le `guild` attendu
    else:
        await ctx.send("❌ Réinitialisation annulée.")


@bot.command()
@commands.has_permissions(administrator=True)
async def setpoints(ctx, type_action: str, gagnants: int, perdants: int, points: float):
    """Définit le nombre de points pour une configuration (admin uniquement)"""
    if type_action not in ["attaque", "défense"]:
        await ctx.send("⚠️ Le type d'action doit être 'attaque' ou 'défense'.")
        return

    try:
        with open("points_config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}

    if type_action not in config:
        config[type_action] = {}

    config[type_action][f"{gagnants}v{perdants}"] = points

    with open("points_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    await ctx.send(f"✅ Barème mis à jour pour {type_action} : {gagnants}v{perdants} = {points} points.")


# --- Fonction voir les pseudos et points d'un membre ---
@bot.command()
async def user(ctx, membre: discord.Member):
    pseudos = liens_pseudos.get(membre.id, [])
    points = classement_points.get(membre.id, 0)

    embed = discord.Embed(title=f"👤 Infos de l'utilisateur",
                          color=discord.Color.blurple())
    embed.add_field(name="👤 Utilisateur", value=membre.mention, inline=False)
    embed.add_field(name="📊 Points", value=f"{points} pts", inline=False)

    if pseudos:
        embed.add_field(name="🎭 Pseudos liés",
                        value=", ".join(pseudos),
                        inline=False)
    else:
        embed.add_field(name="🎭 Pseudos liés", value="Aucun", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="bareme", aliases=["barème"])
@commands.has_permissions(administrator=True)
async def afficher_bareme(ctx):
    try:
        with open("points_config.json", "r", encoding="utf-8") as f:
            barèmes = json.load(f)
    except Exception as e:
        await ctx.send(f"❌ Erreur lors du chargement des barèmes : {e}")
        return

    def generer_tableau_embed(type_action):
        bar = barèmes.get(type_action)
        if not bar:
            return discord.Embed(
                title=f"📊 Barème pour {type_action.upper()}",
                description="Aucun barème défini.",
                color=discord.Color.orange()
            )

        cles_valides = [k for k in bar if 'v' in k and k.count('v') == 1]
        couples = []
        for k in cles_valides:
            try:
                g, p = map(int, k.split('v'))
                couples.append((g, p))
            except ValueError:
                continue

        if not couples:
            return discord.Embed(
                title=f"📊 Barème pour {type_action.upper()}",
                description="Aucun barème valide trouvé.",
                color=discord.Color.orange()
            )

        max_g = max(g for g, _ in couples)
        max_p = max(p for _, p in couples)
        min_g = 1 if type_action == "défense" else 1
        min_p = 0 if type_action == "attaque" else 1

        entete = "Att\\Def" if type_action == "attaque" else "Def\\Att"
        header = [entete] + [str(p) for p in range(min_p, max_p + 1)]
        lignes = [header]
        for g in range(min_g, max_g + 1):
            ligne = [str(g)]
            for p in range(min_p, max_p + 1):
                valeur = bar.get(f"{g}v{p}", "-")
                ligne.append(str(valeur))
            lignes.append(ligne)

        col_widths = [max(len(lignes[i][j]) for i in range(len(lignes))) for j in range(len(header))]
        lignes_formatees = []
        for ligne in lignes:
            lignes_formatees.append("  ".join(ligne[j].ljust(col_widths[j]) for j in range(len(ligne))))

        tableau_final = "```\n" + "\n".join(lignes_formatees) + "\n```"

        return discord.Embed(
            title=f"📊 Barème pour {type_action.upper()}",
            description=tableau_final,
            color=discord.Color.blue()
        )

    await ctx.send(embed=generer_tableau_embed("attaque"))
    await ctx.send(embed=generer_tableau_embed("défense"))


# --- Fonction mettre à jour le classement ---
@bot.command()
async def classement(ctx):
    await mettre_a_jour_classement_epingle(ctx.guild)
    await ctx.send("📌 Classement mis à jour dans le salon dédié.")


# --- Fonction pour traiter les screens de Perco ---
@bot.command()
async def perco(ctx):
    global attente_type, utilisateur_demandeur, pseudos_detectes_actuels
    attente_type = "perco_gagnants"
    utilisateur_demandeur = ctx.author.id
    pseudos_detectes_actuels = []
    await ctx.send("📸 Envoyez le screen des **gagnants**.")


class ChoixPercoView(View):

    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.choix_effectue = False

    async def disable_all_buttons(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Attaque", style=discord.ButtonStyle.success)
    async def attaque(self, interaction: discord.Interaction, button: Button):
        if self.choix_effectue:
            return
        self.choix_effectue = True
        await interaction.response.defer()
        await self.disable_all_buttons(interaction)
        await traiter_points(self.ctx, type_action="attaque")

    @discord.ui.button(label="Défense", style=discord.ButtonStyle.danger)
    async def defense(self, interaction: discord.Interaction, button: Button):
        if self.choix_effectue:
            return
        self.choix_effectue = True
        await interaction.response.defer()
        await self.disable_all_buttons(interaction)
        await traiter_points(self.ctx, type_action="défense")


# --- Fonction pour traiter les points ---
async def traiter_points(ctx, type_action):
    global pseudos_non_associes_globaux, action_en_cours
    action_en_cours = type_action
    pseudos_non_associes = []
    pseudos_ajoutes = []

    gagnants = pseudos_detectes_actuels
    perdants = pseudos_detectes_perdants  # Cette variable doit être remplie avec la commande !perco

    nb_gagnants = len(gagnants)
    nb_perdants = len(perdants)

    # Déterminer les points à attribuer selon la configuration
    config = points_config.get(type_action, {})
    points = config.get(f"{nb_gagnants}v{nb_perdants}", 0)

    for pseudo in gagnants:
        trouve = False
        for discord_id, pseudos in liens_pseudos.items():
            if pseudo in pseudos:
                classement_points[discord_id] = classement_points.get(
                    discord_id, 0) + points
                pseudos_ajoutes.append(pseudo)
                trouve = True
                break
        if not trouve:
            pseudos_non_associes.append(pseudo)

    pseudos_non_associes_globaux = pseudos_non_associes.copy()

    embed = discord.Embed(title="📊 Points ajoutés au classement",
                          color=discord.Color.green())

    if pseudos_ajoutes:
        ajouts = "\n".join(f"✅ {points} points ajoutés à : {pseudo}"
                           for pseudo in pseudos_ajoutes)
        embed.add_field(name="✅ Points ajoutés", value=ajouts, inline=False)
        await mettre_a_jour_classement_epingle(ctx.guild)

    if pseudos_non_associes:
        non_associes = "\n".join(f"• {pseudo}"
                                 for pseudo in pseudos_non_associes)
        embed.add_field(name="🔍 Personnages non associés",
                        value=non_associes,
                        inline=False)

    if pseudos_ajoutes:
        total_points = len(pseudos_ajoutes) * points
        embed.add_field(name="📈 Total",
                        value=f"{total_points} points ajoutés",
                        inline=False)

    if len(embed.fields) > 0:
        await ctx.send(embed=embed)

    sauvegarder_donnees()


def sauvegarder_donnees():
    with open("liens_pseudos.json", "w", encoding="utf-8") as f:
        json.dump(liens_pseudos, f, ensure_ascii=False, indent=2)
    with open("classement_points.json", "w", encoding="utf-8") as f:
        json.dump(classement_points, f, ensure_ascii=False, indent=2)


def charger_donnees():
    global liens_pseudos, classement_points
    try:
        with open("liens_pseudos.json", "r", encoding="utf-8") as f:
            liens_pseudos = json.load(f)
        # Convertir les clés en entiers (JSON les stocke comme chaînes)
        liens_pseudos = {int(k): v for k, v in liens_pseudos.items()}
    except FileNotFoundError:
        liens_pseudos = {}

    try:
        with open("classement_points.json", "r", encoding="utf-8") as f:
            classement_points = json.load(f)
        classement_points = {int(k): v for k, v in classement_points.items()}
    except FileNotFoundError:
        classement_points = {}


@bot.event
async def on_message(message):
    global attente_type, pseudos_detectes_actuels, utilisateur_demandeur, pseudos_detectes_perdants

    if message.author == bot.user or message.channel.id != SALON_AUTORISE_ID:
        return

    if attente_type and message.attachments and message.author.id == utilisateur_demandeur:
        image = message.attachments[0]
        if any(image.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            image_bytes = await image.read()
            image_obj = Image.open(io.BytesIO(image_bytes))
            image_crop = recadrage_dynamique(image_obj)
            texte_ocr = pytesseract.image_to_string(image_crop, lang='fra')
            lignes = [ligne.strip() for ligne in texte_ocr.splitlines() if ligne.strip()]
            pseudos = [ligne for ligne in lignes if len(ligne) >= 2 and not any(char in ligne for char in ['%', '@', '#', '|', '=', 'Niveau']) and "do'" not in ligne.lower()]

            if attente_type == "perco_gagnants":
                pseudos_detectes_actuels = pseudos
                attente_type = "perco_perdants"
                await message.channel.send("📸 Maintenant, envoyez le screen des **perdants**.")
                return

            elif attente_type == "perco_perdants":
                pseudos_detectes_perdants = pseudos  # <--- correction ici
                attente_type = None
                utilisateur_demandeur = None

                score = f"{len(pseudos_detectes_actuels)}V{len(pseudos_detectes_perdants)}"
                embed = discord.Embed(title=f"🏆 Résultat - Victoire {score}", color=discord.Color.blue())
                gagnants = "\n".join(f"- {p}" for p in pseudos_detectes_actuels) or "Aucun"
                perdants = "\n".join(f"- {p}" for p in pseudos_detectes_perdants) or "Aucun"
                embed.add_field(name="🎉 Gagnants", value=gagnants, inline=True)
                embed.add_field(name="😢 Perdants", value=perdants, inline=True)
                await message.channel.send(embed=embed)
                await message.channel.send("👉 Choisissez une action :", view=ChoixPercoView(message.channel))
                return

    await bot.process_commands(message)

# --- Lancement du bot ---
token = os.getenv('TOKEN_PEPITAS')
bot.run(token)
