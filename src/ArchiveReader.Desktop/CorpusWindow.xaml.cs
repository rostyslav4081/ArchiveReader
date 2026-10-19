using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
namespace ArchiveReader;
public partial class CorpusWindow:Window
{
 readonly string? page;readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
 CancellationTokenSource? work;JsonObject? selected;bool busy,loading;
 static string T(string s)=>Localizer.Text(s);
 Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,work?.Token??default);
 public CorpusWindow(string? page,string model,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
 {
  this.page=page;this.worker=worker;InitializeComponent();ModelA.Text=string.IsNullOrWhiteSpace(model)?FindModel("german-handwriting/model.mlmodel")??"":model;ModelB.Text=FindModel("polish-metrical-experimental")??"";
  Loaded+=async(_,_)=>await Run(async()=>{Localizer.Apply(this,Localizer.Language);await Refresh();if(Environment.GetCommandLineArgs().Contains("--smoke-corpus")){if(References.Items.Count>0&&References.Items[0] is GenealogyRow row)await LoadReference(row);Tabs.IsEnabled=true;for(int i=0;i<Tabs.Items.Count;i++){Tabs.SelectedIndex=i;SmokeCapture.Save(this,"corpus-ui",$"tab-{i}.png");}Tabs.SelectedIndex=0;FieldsPanel.IsExpanded=true;FieldsPanel.BringIntoView();SmokeCapture.Save(this,"corpus-ui","fields.png");Close();}});Closing+=(_,_)=>work?.Cancel();
 }
 static string? FindModel(string relative){for(var folder=new DirectoryInfo(AppContext.BaseDirectory);folder!=null;folder=folder.Parent){var candidate=Path.Combine(folder.FullName,"models",relative.Replace('/',Path.DirectorySeparatorChar));if(File.Exists(candidate)||Directory.Exists(candidate))return candidate;}return null;}
 async Task Run(Func<Task> action){if(busy)return;busy=true;work=new();Tabs.IsEnabled=false;References.IsEnabled=false;try{await action();}catch(OperationCanceledException){Status.Text=T("Обробку зупинено. Збережені результати залишилися в бібліотеці.");}catch(Exception ex){Status.Text=T(ex.Message);SmokeCapture.Fail(ex);}finally{Tabs.IsEnabled=true;References.IsEnabled=true;work.Dispose();work=null;busy=false;}}
 void Stop(object s,RoutedEventArgs e)=>work?.Cancel();
 static string Reason(JsonNode? value)=>T(value?.ToString() switch{"draft"=>"Чернетка","damaged"=>"Пошкоджений запис","uncertain_text"=>"Непевний текст","reading_order_required"=>"Потрібен порядок читання","source_changed"=>"Розмітка змінилася","source_or_split_changed"=>"Джерело або роль книги змінилися",_=>"Допущено до перевірки"});
 async Task Refresh()=>References.ItemsSource=(await Call("corpus_list")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["name"]+" · "+n["number"]+"\n"+Reason(n["excluded"]))).ToList();
 async void RefreshEntries(object s,RoutedEventArgs e)=>await Run(Refresh);
 async void ImportEntries(object s,RoutedEventArgs e)=>await Run(async()=>{if(page==null)throw new Exception(T("Спочатку відкрийте сторінку з розміткою записів."));var r=await Call("corpus_import",new(){["id"]=page});await Refresh();Status.Text=T("Чернеток додано")+": "+r["added"]+" · "+T("Без змін")+": "+r["unchanged"];});
 async Task LoadReference(GenealogyRow row)
 {
  selected=row.Data;Locator.Text=row.Data["name"]+" · "+row.Data["number"]+" · "+Reason(row.Data["excluded"]);loading=true;ReferenceText.Text=row.Data["text"]!.ToString();Notes.Text=row.Data["notes"]?.ToString()??"";Verified.IsChecked=row.Data["human_verified"]!.GetValue<bool>();SingleBlock.IsChecked=row.Data["single_block"]!.GetValue<bool>();
  foreach(var field in FieldEditors())field.Editor.Text=row.Data["fields"]?[field.Key]?.ToString()??"";
  FieldsVerified.IsChecked=row.Data["fields_verified"]?.GetValue<bool>()??false;loading=false;
  var crop=await Call("region_crop",new(){["id"]=row.Data["page"]!.ToString(),["annotation"]=row.Data["annotation"]!.ToString()});var b=new BitmapImage();b.BeginInit();b.CacheOption=BitmapCacheOption.OnLoad;b.UriSource=new Uri(crop["path"]!.ToString());b.EndInit();b.Freeze();Scan.Source=b;
  var history=(await Call("corpus_history",new(){["reference"]=row.Data["id"]!.ToString()})).AsArray();History.Text=string.Join("\n\n",history.Select(h=>h!["created"]+" · "+T(h["after"]!["human_verified"]!.GetValue<bool>()?"Підтверджено людиною":"Чернетка")+"\n"+h["after"]!["text"]));
 }
 async void SelectReference(object s,SelectionChangedEventArgs e){if(busy||References.SelectedItem is not GenealogyRow row)return;await Run(()=>LoadReference(row));}
 (string Key,System.Windows.Controls.TextBox Editor)[] FieldEditors()=>new[]{("person",FieldPerson),("date",FieldDate),("house",FieldHouse),("place",FieldPlace),("related1",FieldRelative1),("related2",FieldRelative2),("age",FieldAge)};
 JsonObject ReferenceFields(){var fields=new JsonObject();foreach(var field in FieldEditors())if(!string.IsNullOrWhiteSpace(field.Editor.Text))fields[field.Key]=field.Editor.Text;return fields;}
 void FieldsEdited(object s,TextChangedEventArgs e){if(!loading&&FieldsVerified!=null)FieldsVerified.IsChecked=false;}
 void TextEdited(object s,TextChangedEventArgs e){if(!loading&&Verified!=null){Verified.IsChecked=false;if(FieldsVerified!=null)FieldsVerified.IsChecked=false;}}
 async void SaveReference(object s,RoutedEventArgs e)=>await Run(async()=>{if(selected==null)return;var result=await Call("corpus_save",new(){["reference"]=selected["id"]!.ToString(),["revision"]=selected["revision"]!.ToString(),["text"]=ReferenceText.Text,["notes"]=Notes.Text,["single_block"]=SingleBlock.IsChecked==true,["human_verified"]=Verified.IsChecked==true,["fields"]=ReferenceFields(),["fields_verified"]=FieldsVerified.IsChecked==true});var ident=selected["id"]!.ToString();await Refresh();var row=References.Items.Cast<GenealogyRow>().First(r=>r.Data["id"]!.ToString()==ident);await LoadReference(row);Status.Text=T("Збережено");});
 async void Freeze(object s,RoutedEventArgs e)=>await Run(async()=>{var r=await Call("corpus_freeze");Snapshot.Text=r["path"]!.ToString();Status.Text=T("Записів у знімку")+": "+r["entries"]+" · "+T("Виключено")+": "+r["excluded"];});
 void ChooseSnapshot(object s,RoutedEventArgs e){var d=new OpenFolderDialog();if(d.ShowDialog()==true)Snapshot.Text=d.FolderName;}
 void ChooseModel(object s,RoutedEventArgs e){bool first=((Button)s).Tag.ToString()=="A";var target=first?ModelA:ModelB;if(!first&&((ComboBoxItem)EngineB.SelectedItem).Tag.ToString()=="trocr"){var d=new OpenFolderDialog();if(d.ShowDialog()==true)target.Text=d.FolderName;}else{var d=new OpenFileDialog{Filter="Kraken|*.mlmodel;*.safetensors"};if(d.ShowDialog()==true)target.Text=d.FileName;}}
 JsonArray Models(){if(string.IsNullOrWhiteSpace(ModelA.Text)||string.IsNullOrWhiteSpace(ModelB.Text))throw new Exception(T("Виберіть дві локальні моделі."));return new(new JsonObject{["name"]="A",["engine"]="kraken",["path"]=ModelA.Text},new JsonObject{["name"]="B",["engine"]=((ComboBoxItem)EngineB.SelectedItem).Tag.ToString(),["path"]=ModelB.Text});}
 static string Rate(JsonNode? n)=>n==null?"—":(n.GetValue<double>()*100).ToString("F1")+"%";
 async void CompareEntries(object s,RoutedEventArgs e)=>await Run(async()=>{if(string.IsNullOrWhiteSpace(Snapshot.Text))throw new Exception(T("Спочатку зафіксуйте перевірений корпус."));var r=await Call("corpus_compare",new(){["path"]=Snapshot.Text,["models"]=Models()});Summary.Text=string.Join("\n",r["models"]!.AsArray().Select(m=>m!["name"]+": CER "+Rate(m["micro_cer"])+" · WER "+Rate(m["micro_wer"])+" · "+T("Збоїв")+": "+m["failed_entries"]+" · "+T("Спільний CER")+": "+Rate(m["common_cer"])+" · "+T("Час розпізнавання, с")+": "+m["recognition_seconds"]))+"\n"+T("Спільних успішних записів")+": "+r["common_entries"]+"\n"+r["path"];Summary.Text+="\n\n"+T("Придатність лише на перевірених записах цієї книги")+"\n"+string.Join("\n",r["suitability"]!["books"]!.AsArray().Select(b=>b!["name"]+": "+(b["lowest_observed_cer_model"]?.ToString()??T("Переможця не визначено"))+" · "+T("Спільних успішних записів")+": "+b["common_entries"]+(b["small_sample"]!.GetValue<bool>()?" · "+T("Мала вибірка; висновок попередній"):"")));Results.ItemsSource=r["entries"]!.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["book_name"]+" · "+n["page"])).ToList();Results.SelectedIndex=0;});
 void SelectResult(object s,SelectionChangedEventArgs e){if(Results.SelectedItem is not GenealogyRow row)return;ResultText.Text=T("Еталон")+":\n"+row.Data["text"]+"\n\n"+string.Join("\n\n",row.Data["results"]!.AsObject().Select(r=>r.Key+":\n"+(r.Value?["text"]??r.Value?["error"])));}
 void ChooseFieldPredictions(object sender,RoutedEventArgs e){var dialog=new OpenFileDialog{Filter=T("Таблиця прочитаних полів")+"|*.json"};if(dialog.ShowDialog()==true)FieldPredictions.Text=dialog.FileName;}
 static string FieldName(string key)=>T(key switch{"person"=>"Ім’я та прізвище","date"=>"Дата події","house"=>"Номер будинку","place"=>"Населений пункт","related1"=>"Родич 1","related2"=>"Родич 2","age"=>"Вік",_=>"Поле"});
 async void ScoreFields(object sender,RoutedEventArgs e)=>await Run(async()=>
 {
  if(string.IsNullOrWhiteSpace(Snapshot.Text)||string.IsNullOrWhiteSpace(FieldPredictions.Text))throw new Exception(T("Виберіть знімок корпусу й файл прочитаних полів."));
  if(new FileInfo(FieldPredictions.Text).Length>2_000_000)throw new Exception(T("Файл прочитаних полів завеликий."));
  var input=JsonNode.Parse(await File.ReadAllTextAsync(FieldPredictions.Text));
  var predictions=input as JsonArray??(input as JsonObject)?["predictions"] as JsonArray;
  if(predictions==null)throw new Exception(T("Файл не містить списку прочитаних полів."));
  string manifest=Path.Combine(Snapshot.Text,"manifest.json");using var stream=File.OpenRead(manifest);string sha=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(stream)).ToLowerInvariant();
  var result=await Call("corpus_score_fields",new(){["path"]=Snapshot.Text,["expected_manifest_sha256"]=sha,["predictions"]=predictions.DeepClone(),["model"]=input is JsonObject&&input["model"] is JsonObject supplied?supplied.DeepClone():new JsonObject{["name"]=Path.GetFileName(FieldPredictions.Text)}});
  FieldSummary.Text=string.Join("\n\n",result["metrics"]!.AsObject().Select(pair=>FieldName(pair.Key)+": "+T("Точних значень")+" "+pair.Value!["exact"]+"/"+pair.Value["references"]+" ("+Rate(pair.Value["exact_rate_all_references"])+") · "+T("Пропусків")+": "+pair.Value["missing"]+" · "+T("Збоїв")+": "+pair.Value["failed"]+" · CER "+Rate(pair.Value["cer_successful_predictions"])))+"\n\n"+result["path"];
 });

}
