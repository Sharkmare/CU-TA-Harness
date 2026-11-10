using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private const float AutoPickupDistance = 2f;
        private const int DefaultTapFrames = 3;

        private static Body RequirePlayer()
        {
            if (!GameState.InWorld) throw new Exception("not in a world (state is " + GameState.Name() + ")");
            return PlayerCamera.main.body;
        }

        private static void RegisterWorld()
        {
            Add("spawn", "Creates an item or entity by resource id near the player (or at x,y). Items within 2 units are auto picked up, like the console spawn command.", args =>
            {
                Body body = RequirePlayer();
                string id = Str(args, "id", null, true);
                Vector2 position = args["x"] != null && args["y"] != null ? new Vector2(Float(args, "x", 0), Float(args, "y", 0)) : (Vector2)body.transform.position;
                float condition = Float(args, "condition", 1f);
                int amount = Int(args, "amount", 1);
                var created = new List<object>();
                for (int i = 0; i < amount; i++)
                {
                    GameObject spawned = Utils.Create(id, position, 0f);
                    if (spawned == null) throw new Exception("no resource named '" + id + "'");
                    bool pickedUp = false;
                    if (spawned.TryGetComponent<Item>(out Item item))
                    {
                        item.SetCondition(condition);
                        if (Bool(args, "pickup", true) && Vector2.Distance(spawned.transform.position, body.transform.position) < AutoPickupDistance)
                        {
                            body.AutoPickUpItem(item);
                            pickedUp = body.SlotOf(item) >= 0 || item.ParentContainer() != null;
                        }
                    }
                    created.Add(new Dictionary<string, object> { { "object", Reflect.Handle(spawned) }, { "pickedUp", pickedUp } });
                }
                return created;
            }, false,
                Arg("id", "string", "Resource path id such as the game's spawn command takes", true),
                Arg("x", "float", "World x; defaults to the player"), Arg("y", "float", "World y; defaults to the player"),
                Arg("condition", "float", "Item condition 0 to 1", false, 1f), Arg("amount", "int", "How many", false, 1),
                Arg("pickup", "bool", "Auto pick up when near the player", false, true));

            Add("list_items", "Lists Item components in the world with id, position, condition and whether the player holds them.", args =>
            {
                string filter = Str(args, "id");
                int limit = Int(args, "limit", 100);
                Body body = GameState.InWorld ? PlayerCamera.main.body : null;
                var rows = new List<object>();
                foreach (Item item in UnityEngine.Object.FindObjectsOfType<Item>())
                {
                    if (filter != null && (item.id == null || item.id.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0)) continue;
                    int slot = body != null ? body.SlotOf(item) : -1;
                    rows.Add(new Dictionary<string, object>
                    {
                        { "id", item.id }, { "object", Reflect.Handle(item) }, { "condition", item.condition },
                        { "position", Reflect.Serialize((Vector2)item.transform.position, 0) }, { "slot", slot },
                        { "distance", body != null ? Vector2.Distance(item.transform.position, body.transform.position) : -1f },
                    });
                    if (rows.Count >= limit) break;
                }
                return rows;
            }, false, Arg("id", "string", "Substring filter on item id"), Arg("limit", "int", "Maximum rows", false, 100));

            Add("player", "Snapshot of the player Body: plain fields, skills, every Limb, inventory slots, position.", args =>
            {
                Body body = RequirePlayer();
                var limbs = new List<object>();
                for (int i = 0; i < body.limbs.Length; i++)
                {
                    Dictionary<string, object> fields = Reflect.PlainFields(body.limbs[i]);
                    fields["index"] = i;
                    fields["name"] = body.limbs[i].name;
                    limbs.Add(fields);
                }
                var inventory = new List<object>();
                for (int i = 0; i < body.slots.Length; i++)
                {
                    Item held = body.GetItem(i);
                    inventory.Add(new Dictionary<string, object>
                    {
                        { "slot", i }, { "isHand", body.slots[i].isHand },
                        { "item", held == null ? null : new Dictionary<string, object> { { "id", held.id }, { "condition", held.condition }, { "object", Reflect.Handle(held) } } },
                    });
                }
                return new Dictionary<string, object>
                {
                    { "prefab", body.transform.root.name }, { "alive", body.alive },
                    { "position", Reflect.Serialize((Vector2)body.transform.position, 0) },
                    { "body", Reflect.PlainFields(body) }, { "skills", Reflect.PlainFields(body.skills) },
                    { "limbs", limbs }, { "inventory", inventory },
                };
            });

            Add("damage", "Applies Limb.ImpactDamage to one player limb, the same call a hard fall makes. Force above Body.jumpSpeed does damage.", args =>
            {
                Body body = RequirePlayer();
                int index = Int(args, "limb", 0);
                if (index < 0 || index >= body.limbs.Length) throw new Exception("limb index out of range 0.." + (body.limbs.Length - 1));
                body.limbs[index].ImpactDamage(Float(args, "force", 100f), Vector2.down);
                return new Dictionary<string, object> { { "limb", body.limbs[index].name }, { "skinHealth", body.limbs[index].skinHealth }, { "muscleHealth", body.limbs[index].muscleHealth } };
            }, false, Arg("limb", "int", "Index into Body.limbs (see player)", false, 0), Arg("force", "float", "Impact force", false, 100f));

            Add("use_item_on_limb", "Runs the item's limb action (what using a held item on a limb in the wound view does). Medical items open their minigame.", args =>
            {
                Body body = RequirePlayer();
                Item item = body.GetItem(Int(args, "slot", 0));
                if (item == null) throw new Exception("slot is empty");
                int index = Int(args, "limb", 0);
                ItemInfo info = Item.GetItem(item.id);
                if (info == null || info.useLimbAction == null) throw new Exception("item '" + item.id + "' has no limb action");
                info.useLimbAction(body.limbs[index], item);
                return new Dictionary<string, object> { { "item", item.id }, { "limb", body.limbs[index].name } };
            }, false, Arg("slot", "int", "Inventory slot of the item", false, 0), Arg("limb", "int", "Index into Body.limbs", false, 0));

            Add("keybinds", "The game's bound key for each action name (KeyBinds), so input can be sent by action.", args =>
            {
                var cache = (Dictionary<string, KeyCode>)typeof(KeyBinds).GetField("cachedBinds", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic).GetValue(null);
                return cache.ToDictionary(pair => pair.Key, pair => pair.Value.ToString());
            });

            Add("input", "Injects a key press through the game's Input calls (not OS input). Name an action from 'keybinds' or a KeyCode. Frame based: held on the N frames after the command.", args =>
            {
                string action = Str(args, "action");
                string keyName = Str(args, "key");
                if (action == null && keyName == null) throw new Exception("give 'action' or 'key'");
                KeyCode key = action != null ? KeyBinds.GetBind(action) : (KeyCode)Enum.Parse(typeof(KeyCode), keyName, true);
                if (key == KeyCode.None) throw new Exception("action '" + action + "' has no bound key (see keybinds)");
                string mode = Str(args, "mode", "tap");
                if (mode == "release") InputInjector.Release(key);
                else InputInjector.Press(key, mode == "hold" ? 0 : Int(args, "frames", DefaultTapFrames));
                return new Dictionary<string, object> { { "key", key.ToString() }, { "mode", mode }, { "frame", Time.frameCount } };
            }, false,
                Arg("action", "string", "KeyBinds action name, e.g. up, attack, console"), Arg("key", "string", "UnityEngine.KeyCode name, e.g. W or Mouse0"),
                Arg("mode", "string", "tap (default), hold (until release) or release", false, "tap"), Arg("frames", "int", "Frames held for tap", false, DefaultTapFrames));

            Add("input_probe", "Calls the real Input.GetKey, GetKeyDown and GetKeyUp for a key now, to show what the game would see this frame.", args =>
            {
                KeyCode key = (KeyCode)Enum.Parse(typeof(KeyCode), Str(args, "key", null, true), true);
                return new Dictionary<string, object>
                {
                    { "key", key.ToString() }, { "frame", Time.frameCount },
                    { "getKey", Input.GetKey(key) }, { "getKeyDown", Input.GetKeyDown(key) }, { "getKeyUp", Input.GetKeyUp(key) },
                    { "injected", InputInjector.Describe() },
                };
            }, false, Arg("key", "string", "UnityEngine.KeyCode name", true));

            Add("mouse", "Sets the injected mouse position in screen pixels, or in world units with wx and wy, or clears it. Mouse buttons go through 'input' with key Mouse0.", args =>
            {
                if (Bool(args, "clear", false)) { InputInjector.MousePosition = null; return InputInjector.Describe(); }
                if (args["wx"] != null)
                    InputInjector.MousePosition = Camera.main.WorldToScreenPoint(new Vector3(Float(args, "wx", 0), Float(args, "wy", 0), 0f));
                else
                    InputInjector.MousePosition = new Vector3(Float(args, "x", 0), Float(args, "y", 0), 0f);
                return InputInjector.Describe();
            }, false,
                Arg("x", "float", "Screen x"), Arg("y", "float", "Screen y"), Arg("wx", "float", "World x"), Arg("wy", "float", "World y"), Arg("clear", "bool", "Stop overriding the mouse"));

            Add("release_input", "Releases every injected key and the injected mouse.", args => { InputInjector.ReleaseAll(); return InputInjector.Describe(); });
        }
    }
}
